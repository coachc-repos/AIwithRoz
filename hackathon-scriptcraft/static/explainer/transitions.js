/* Stylized slide transitions. A pure function of time, so the preview and the
   frame renderer (headless Chrome calling __seek) draw the same frame.
   The effect overlaps both slides. It does not change their text. The wave
   background stays underneath: masks reveal it, and the overlay canvas is
   transparent except for the accent marks. */
(function () {
    'use strict';
    var GOLD = [245, 184, 61];
    var RED = [240, 82, 82];
    var BLUE = [76, 141, 255];
    var CYAN = [90, 220, 255];
    var masks = { inn: null, out: null };
    var maskCache = {};
    var svgReady = false;

    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function hash(s) {
        var h = 2166136261;
        s = String(s);
        for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
        return ((h >>> 0) % 10000) / 10000;
    }
    function smooth(p) { p = clamp(p, 0, 1); return p * p * (3 - 2 * p); }
    function bell(p) { return Math.sin(clamp(p, 0, 1) * Math.PI); }
    function rgba(rgb, a) { return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + a + ')'; }

    function canvasOf(which, w, h) {
        var c = masks[which];
        if (!c) {
            c = document.createElement('canvas');
            masks[which] = c;
        }
        if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
        var g = c.getContext('2d');
        g.setTransform(1, 0, 0, 1, 0, 0);
        g.clearRect(0, 0, w, h);
        return g;
    }
    function maskUrl(which, key) {
        if (maskCache[which] && maskCache[which].key === key) return maskCache[which].url;
        var url = masks[which].toDataURL('image/png');
        maskCache[which] = { key: key, url: url };
        return url;
    }
    function applyMask(el, url, size, pos) {
        var m = url ? 'url("' + url + '")' : 'none';
        el.style.webkitMaskImage = m;
        el.style.maskImage = m;
        el.style.webkitMaskSize = size || '100% 100%';
        el.style.maskSize = size || '100% 100%';
        el.style.webkitMaskRepeat = 'no-repeat';
        el.style.maskRepeat = 'no-repeat';
        el.style.webkitMaskPosition = pos || 'center';
        el.style.maskPosition = pos || 'center';
        // Alpha, not luminance: transparent pixels hide the slide, white shows it.
        // Opaque black would count as visible and the mosaic would never open.
        el.style.webkitMaskMode = 'alpha';
        el.style.maskMode = 'alpha';
    }
    function clearEl(el) {
        if (!el) return;
        el.style.webkitMaskImage = 'none';
        el.style.maskImage = 'none';
        el.style.filter = '';
        el.style.opacity = '';
        el.style.transform = '';
    }

    function ensureSvg() {
        if (svgReady || document.getElementById('xv-fx-svg')) { svgReady = true; return; }
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.id = 'xv-fx-svg';
        svg.setAttribute('aria-hidden', 'true');
        svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
        svg.innerHTML = ''
            + '<filter id="xv-warp" x="-12%" y="-12%" width="124%" height="124%" color-interpolation-filters="sRGB">'
            + '<feTurbulence id="xv-warp-turb" type="turbulence" baseFrequency="0.008 0.018" numOctaves="2" seed="3" result="noise"/>'
            + '<feDisplacementMap id="xv-warp-map" in="SourceGraphic" in2="noise" scale="0" xChannelSelector="R" yChannelSelector="G"/>'
            + '</filter>'
            + '<filter id="xv-blur" x="-8%" y="-4%" width="116%" height="108%">'
            + '<feGaussianBlur id="xv-blur-amt" stdDeviation="0 0"/>'
            + '</filter>';
        document.body.appendChild(svg);
        svgReady = true;
    }
    function fxCanvas() {
        var c = document.getElementById('fx');
        if (!c) {
            var stage = document.getElementById('stage');
            if (!stage) return null;
            c = document.createElement('canvas');
            c.id = 'fx';
            c.width = 1920;
            c.height = 1080;
            stage.appendChild(c);
        }
        return c;
    }
    function overlayCtx() {
        var c = fxCanvas();
        if (!c) return null;
        var k = window.devicePixelRatio || 1;
        if (c.width !== Math.round(1920 * k) || c.height !== Math.round(1080 * k)) {
            c.width = Math.round(1920 * k);
            c.height = Math.round(1080 * k);
        }
        var ctx = c.getContext('2d');
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.clearRect(0, 0, 1920, 1080);
        ctx.globalCompositeOperation = 'source-over';
        ctx.globalAlpha = 1;
        return ctx;
    }

    var inkUrl = {};
    function inkBlob(seed) {
        if (inkUrl[seed]) return inkUrl[seed];
        var c = document.createElement('canvas');
        c.width = 480; c.height = 270;
        var g = c.getContext('2d');
        g.fillStyle = '#fff';
        g.beginPath();
        var cx = 160 + hash(seed + 'x') * 160, cy = 80 + hash(seed + 'y') * 110;
        for (var i = 0; i < 7; i++) {
            var ang = hash(seed + 'a' + i) * 6.283;
            var rad = 70 + hash(seed + 'r' + i) * 90;
            g.moveTo(cx, cy);
            g.bezierCurveTo(
                cx + Math.cos(ang) * rad, cy + Math.sin(ang) * rad * 0.6,
                cx + Math.cos(ang + 1) * rad * 1.3, cy + Math.sin(ang + 0.6) * rad,
                cx + Math.cos(ang + 0.4) * 20, cy + Math.sin(ang + 0.4) * 16);
        }
        g.fill();
        for (var b = 0; b < 5; b++) {
            g.beginPath();
            g.arc(80 + hash(seed + 'b' + b) * 320, 40 + hash(seed + 'c' + b) * 190,
                36 + hash(seed + 'd' + b) * 50, 0, 6.283);
            g.fill();
        }
        inkUrl[seed] = c.toDataURL('image/png');
        return inkUrl[seed];
    }

    function bandMask(p, seed, incoming) {
        var g = canvasOf(incoming ? 'inn' : 'out', 32, 270);
        var bands = 16;
        var gap = 4;
        var bh = 270 / bands;
        g.fillStyle = '#fff';
        for (var i = 0; i < bands; i++) {
            var thresh = hash(seed + ':b:' + i) * 0.82;
            var on = p >= thresh;
            if (Math.abs(p - thresh) < 0.07 && hash(seed + ':f:' + i + ':' + Math.floor(p * 18)) > 0.55) on = !on;
            if (!(incoming ? on : !on)) continue;
            var y = Math.round(i * bh);
            var h = Math.max(1, Math.round(bh) - gap);
            g.fillRect(0, y, 32, h);
        }
        return maskUrl(incoming ? 'inn' : 'out', 'band:' + seed + ':' + (incoming ? 1 : 0) + ':' + Math.round(p * 24));
    }
    function pixelMask(p, seed, incoming) {
        var cols = 16, rows = 9, cw = 30, ch = 30;
        var g = canvasOf(incoming ? 'inn' : 'out', cols * cw, rows * ch);
        var eased = smooth(p);
        g.fillStyle = '#fff';
        for (var y = 0; y < rows; y++) {
            for (var x = 0; x < cols; x++) {
                var on = hash(seed + ':' + x + ':' + y) < eased;
                if (incoming ? on : !on) g.fillRect(x * cw, y * ch, cw, ch);
            }
        }
        return maskUrl(incoming ? 'inn' : 'out', 'pix:' + seed + ':' + (incoming ? 1 : 0) + ':' + Math.round(eased * 20));
    }
    function wedgeMask(p, seed, incoming) {
        var g = canvasOf(incoming ? 'inn' : 'out', 320, 180);
        g.fillStyle = '#fff';
        var n = 10;
        var cx = 160, cy = 90;
        for (var i = 0; i < n; i++) {
            var on = p >= hash(seed + ':w:' + i) * 0.78;
            if (!(incoming ? on : !on)) continue;
            var a0 = i / n * 6.283 - 0.04;
            var a1 = (i + 1) / n * 6.283 + 0.04;
            g.beginPath();
            g.moveTo(cx, cy);
            g.lineTo(cx + Math.cos(a0) * 240, cy + Math.sin(a0) * 160);
            g.lineTo(cx + Math.cos(a1) * 240, cy + Math.sin(a1) * 160);
            g.closePath();
            g.fill();
        }
        return maskUrl(incoming ? 'inn' : 'out', 'wedge:' + seed + ':' + (incoming ? 1 : 0) + ':' + Math.round(p * 20));
    }

    function setWarp(scale, p) {
        ensureSvg();
        var map = document.getElementById('xv-warp-map');
        var turb = document.getElementById('xv-warp-turb');
        if (map) map.setAttribute('scale', scale.toFixed(2));
        if (turb) turb.setAttribute('baseFrequency', (0.006 + 0.004 * Math.sin(p * 8)).toFixed(4) + ' 0.02');
    }
    function setBlur(x) {
        ensureSvg();
        var node = document.getElementById('xv-blur-amt');
        if (node) node.setAttribute('stdDeviation', x.toFixed(2) + ' 0.15');
    }

    function paint(slide, fx) {
        var el = slide.el;
        var incoming = slide === fx.inn;
        var p = fx.p, amp = fx.amp || 1;
        var seed = (fx.inn && fx.inn.el && fx.inn.el.id) || 'fx';
        var o = 1;
        el.style.filter = '';
        applyMask(el, '', '100% 100%', 'center');
        el.style.transform = '';
        if (p > 0.985) { el.style.opacity = ''; return 1; }
        if (fx.style === 'glitch') {
            var url = bandMask(p, seed, incoming);
            applyMask(el, url, '100% 100%', 'center');
            var dx = Math.sin(p * 22) * 16 * amp * bell(p);
            var jx = Math.sin(p * 40 + (incoming ? 0 : 1)) * 10 * amp * bell(p);
            if (Math.abs(dx) > 0.6) {
                el.style.filter = 'drop-shadow(' + dx.toFixed(1) + 'px 0 0 rgba(240,40,80,0.8)) drop-shadow('
                    + (-dx).toFixed(1) + 'px 0 0 rgba(40,210,255,0.72))';
            }
            el.style.transform = 'translateX(' + jx.toFixed(2) + 'px)';
            o = 1;
        } else if (fx.style === 'paint' || fx.style === 'burn') {
            if (incoming) {
                var grow = 18 + smooth(p) * (fx.style === 'burn' ? 280 : 250);
                applyMask(el, inkBlob(seed + fx.style), grow.toFixed(1) + '% ' + (grow * 0.92).toFixed(1) + '%',
                    fx.style === 'burn' ? '88% 12%' : '42% 46%');
                o = 1;
            } else {
                o = p < 0.62 ? 1 : 1 - (p - 0.62) / 0.38;
            }
        } else if (fx.style === 'warp') {
            var sc = bell(p) * 46 * amp;
            setWarp(sc, p);
            el.style.filter = sc > 0.8 ? 'url(#xv-warp)' : '';
            var fade = smooth(p);
            o = incoming ? fade : (1 - fade * 0.92);
            var z = 1 + 0.018 * bell(p) * amp;
            el.style.transform = 'scale(' + z.toFixed(4) + ')';
        } else if (fx.style === 'pixel') {
            applyMask(el, pixelMask(p, seed, incoming), '100% 100%', 'center');
            o = 1;
        } else if (fx.style === 'lightleak') {
            var whip = smooth(p);
            var blur = bell(p) * 9 * amp;
            setBlur(blur);
            el.style.filter = blur > 0.4 ? 'url(#xv-blur)' : '';
            if (incoming) {
                o = clamp(p * 1.35, 0, 1);
                el.style.transform = 'translateX(' + ((1 - whip) * 190 * amp).toFixed(2) + 'px) scale(' + (1.16 - 0.16 * whip).toFixed(4) + ')';
            } else {
                o = clamp(1 - p * 1.12, 0, 1);
                el.style.transform = 'translateX(' + (-whip * 240 * amp).toFixed(2) + 'px) scale(' + (1 + 0.04 * bell(p)).toFixed(4) + ')';
            }
        } else if (fx.style === 'shatter') {
            applyMask(el, wedgeMask(p, seed, incoming), '100% 100%', 'center');
            o = 1;
        }
        el.style.opacity = o >= 0.999 ? '' : Math.max(0, o).toFixed(3);
        return o;
    }

    function drawGlitch(ctx, p, amp, seed) {
        var b = bell(p) * amp;
        ctx.fillStyle = 'rgba(0,0,0,' + (0.18 * b).toFixed(3) + ')';
        for (var y = 0; y < 1080; y += 4) ctx.fillRect(0, y, 1920, 1);
        for (var i = 0; i < 5; i++) {
            var yy = Math.floor(hash(seed + ':y:' + i + ':' + Math.floor(p * 12)) * 1000);
            var h = 6 + Math.floor(hash(seed + ':h:' + i) * 16);
            var rgb = i % 3 === 0 ? RED : i % 3 === 1 ? CYAN : GOLD;
            ctx.fillStyle = rgba(rgb, 0.28 * b);
            ctx.fillRect(-40 + hash(seed + ':x:' + i) * 80, yy, 1920, h);
        }
        if (b > 0.35) {
            for (var n = 0; n < 70; n++) {
                var nx = hash(seed + ':n' + n + Math.floor(p * 10)) * 1920;
                var ny = hash(seed + ':m' + n) * 1080;
                ctx.fillStyle = 'rgba(242,244,248,' + (0.15 + 0.2 * hash(seed + n)).toFixed(3) + ')';
                ctx.fillRect(nx, ny, 3 + hash(seed + 'w' + n) * 18, 2);
            }
        }
    }
    function drawInk(ctx, p, amp, seed, burn) {
        var edge = bell(p) * amp;
        if (edge < 0.04) return;
        var grow = 0.15 + smooth(p) * 1.35;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        for (var i = 0; i < 6; i++) {
            var ang = hash(seed + 'e' + i) * 6.283;
            var rad = (220 + i * 70) * grow;
            var cx = burn ? 1500 : 820, cy = burn ? 220 : 500;
            ctx.beginPath();
            ctx.strokeStyle = rgba(i % 2 ? (burn ? RED : BLUE) : GOLD, (burn ? 0.55 : 0.4) * edge);
            ctx.lineWidth = burn ? 18 + i * 3 : 14 + i * 2;
            ctx.arc(cx, cy, rad, ang, ang + 0.9 + hash(seed + 's' + i));
            ctx.stroke();
        }
        if (burn && p < 0.25) {
            ctx.fillStyle = 'rgba(255,220,140,' + (0.22 * (1 - p / 0.25)).toFixed(3) + ')';
            ctx.beginPath();
            ctx.arc(1580, 160, 180, 0, 6.283);
            ctx.fill();
        }
    }
    function drawPixel(ctx, p, amp, seed) {
        var cols = 16, rows = 9, cw = 1920 / cols, ch = 1080 / rows;
        var eased = smooth(p);
        for (var y = 0; y < rows; y++) {
            for (var x = 0; x < cols; x++) {
                var h = hash(seed + ':' + x + ':' + y);
                if (Math.abs(h - eased) > 0.08) continue;
                ctx.fillStyle = rgba((x + y) % 2 ? GOLD : BLUE, 0.22 * amp);
                ctx.fillRect(x * cw + 2, y * ch + 2, cw - 4, ch - 4);
            }
        }
    }
    function drawLeak(ctx, p, amp) {
        var b = bell(p) * amp;
        var g1 = ctx.createRadialGradient(180, 280, 40, 220, 320, 820);
        g1.addColorStop(0, rgba(GOLD, 0.55 * b));
        g1.addColorStop(1, rgba(GOLD, 0));
        ctx.fillStyle = g1;
        ctx.fillRect(0, 0, 1920, 1080);
        var g2 = ctx.createRadialGradient(1700, 760, 20, 1600, 700, 700);
        g2.addColorStop(0, rgba(BLUE, 0.40 * b));
        g2.addColorStop(1, rgba(BLUE, 0));
        ctx.fillStyle = g2;
        ctx.fillRect(0, 0, 1920, 1080);
        if (p < 0.16) {
            ctx.fillStyle = 'rgba(255,248,230,' + (0.42 * (1 - p / 0.16) * amp).toFixed(3) + ')';
            ctx.fillRect(0, 0, 1920, 1080);
        }
    }
    function drawShatter(ctx, p, amp, seed) {
        var a = (1 - smooth(p)) * 0.85 * amp;
        if (a < 0.03) return;
        ctx.strokeStyle = rgba(GOLD, a);
        ctx.lineWidth = 3;
        var n = 10, cx = 960, cy = 540;
        for (var i = 0; i < n; i++) {
            var ang = (i / n) * 6.283 + hash(seed + i) * 0.05;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(cx + Math.cos(ang) * 1100, cy + Math.sin(ang) * 700);
            ctx.stroke();
        }
        for (var s = 0; s < 8; s++) {
            var ang2 = hash(seed + 's' + s) * 6.283;
            var dist = (1 - p) * (180 + hash(seed + 'd' + s) * 420);
            ctx.fillStyle = rgba(s % 2 ? BLUE : GOLD, 0.18 * a);
            ctx.save();
            ctx.translate(cx + Math.cos(ang2) * dist, cy + Math.sin(ang2) * dist * 0.6);
            ctx.rotate(ang2);
            ctx.fillRect(-28, -10, 56, 20);
            ctx.restore();
        }
    }
    function drawWaves(ctx, p, amp) {
        var a = 0.22 * bell(p) * amp;
        if (a < 0.02) return;
        ctx.strokeStyle = rgba(BLUE, a);
        ctx.lineWidth = 2;
        for (var r = 0; r < 4; r++) {
            ctx.beginPath();
            var y0 = 620 + r * 70;
            for (var x = 0; x <= 1920; x += 24) {
                var y = y0 + Math.sin(x / 180 + p * 6 + r) * (10 + r * 4);
                if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
        }
    }

    function roleOf(el, media, t, strict) {
        var fx = window.XVFx.current;
        if (!fx || !media) return '';
        var t0 = +media.t0, t1 = +media.t1;
        if (Math.abs(t0 - fx.inn.t0) < 0.06 && t < t1) return 'inn';
        if (Math.abs(t1 - fx.inn.t0) < 0.06 && t >= t1 - 0.02) return 'out';
        if (!strict && t >= t1) return 'out';
        return '';
    }

    window.XVFx = {
        current: null,
        prepare: function (slides) {
            var known = { glitch: 1, paint: 1, warp: 1, pixel: 1, lightleak: 1, burn: 1, shatter: 1 };
            slides.forEach(function (s) {
                var name = (s.el.dataset.fx || '').toLowerCase();
                s.fx = known[name] ? name : '';
                s.fxDur = s.fx ? Math.max(0.2, +s.el.dataset.fxDur || 0.5) : 0;
                s.fxAmp = s.fx ? clamp(+s.el.dataset.fxAmp || 1, 0.15, 1) : 0;
            });
            ensureSvg();
            fxCanvas();
        },
        tail: function (slide, slides, tr) {
            var n = slides[slide.i + 1];
            if (n && n.fx) return n.fxDur;
            if (!n || n.trans === 'cut') return 0;
            return tr;
        },
        active: function (slides, t) {
            for (var i = 1; i < slides.length; i++) {
                var s = slides[i];
                if (!s.fx) continue;
                if (t >= s.t0 && t < s.t0 + s.fxDur - 1e-4) {
                    return { inn: s, out: slides[i - 1], p: (t - s.t0) / s.fxDur, style: s.fx, amp: s.fxAmp || 1, dur: s.fxDur };
                }
            }
            return null;
        },
        paint: paint,
        clear: function (slide) { clearEl(slide && slide.el); },
        clipExtra: function (clip, slides) {
            var t1 = +clip.t1;
            for (var i = 0; i < slides.length; i++) {
                var s = slides[i];
                if (s.fx && Math.abs(s.t0 - t1) < 0.05) return s.fxDur;
            }
            return 0;
        },
        clearMedia: clearEl,
        styleMedia: function (el, media, t, strict) {
            var fx = window.XVFx.current;
            var role = roleOf(el, media, t, strict);
            if (!fx || !role) { clearEl(el); return; }
            var fake = role === 'inn' ? fx.inn : fx.out;
            if (!fake) { clearEl(el); return; }
            var saved = fake.el;
            fake.el = el;
            paint(fake, fx);
            fake.el = saved;
        },
        overlay: function (fx) {
            var ctx = overlayCtx();
            if (!ctx || !fx) return;
            var seed = (fx.inn && fx.inn.el && fx.inn.el.id) || 'fx';
            if (fx.style === 'glitch') drawGlitch(ctx, fx.p, fx.amp, seed);
            else if (fx.style === 'paint') drawInk(ctx, fx.p, fx.amp, seed, false);
            else if (fx.style === 'burn') drawInk(ctx, fx.p, fx.amp, seed, true);
            else if (fx.style === 'pixel') drawPixel(ctx, fx.p, fx.amp, seed);
            else if (fx.style === 'lightleak') drawLeak(ctx, fx.p, fx.amp);
            else if (fx.style === 'shatter') drawShatter(ctx, fx.p, fx.amp, seed);
            else if (fx.style === 'warp') drawWaves(ctx, fx.p, fx.amp);
        }
    };
})();
