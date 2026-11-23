/* Stylized slide transitions. A pure function of time, so the preview and the
   frame renderer (headless Chrome calling __seek) draw the same frame.
   The effect overlaps both slides. It does not change their text. The wave
   background stays underneath: masks reveal it, and the overlay canvas is
   transparent except for the accent marks.

   Reveals use two inline SVG <mask> elements (one for the incoming slide,
   one for the outgoing slide). Both are drawn from the same shape each
   frame, so the two slides never overlap, and a vector mask needs no image
   decode before the frame is captured. Content units are the element's own
   box, so a clip or demo pane uses the same shape scaled to its size.

   Styles: glitch, paint (ink bleed), warp, pixel, lightleak, burn (film
   burn), shatter (shown as "Strobe wipe": a steady light bar sweeps left to
   right; no flicker). */
(function () {
    'use strict';
    var W = 1920, H = 1080, TAU = Math.PI * 2;
    var GOLD = [245, 184, 61];
    var RED = [240, 82, 82];
    var BLUE = [76, 141, 255];
    var CYAN = [90, 220, 255];
    var SVGNS = 'http://www.w3.org/2000/svg';
    var svgReady = false;
    var maskPaths = null;

    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function strSeed(s) {
        var h = 2166136261;
        s = String(s);
        for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
        return h >>> 0;
    }
    // Integer hash to [0, 1). Exact in every engine, so a frame is the same
    // in the preview and in the renderer.
    function ih(a, b, c) {
        var h = Math.imul((a | 0) ^ 0x9e3779b9, 0x85ebca6b);
        h ^= Math.imul((b | 0) + 0x7f4a7c15, 0xc2b2ae35);
        h = Math.imul(h ^ (h >>> 13), 0x27d4eb2d);
        h ^= Math.imul((c | 0) + 0x165667b1, 0x9e3779b1);
        h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
        h ^= h >>> 16;
        return (h >>> 0) / 4294967296;
    }
    function smooth(p) { p = clamp(p, 0, 1); return p * p * (3 - 2 * p); }
    function bell(p) { return Math.sin(clamp(p, 0, 1) * Math.PI); }
    function rgba(rgb, a) { return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + clamp(a, 0, 1).toFixed(3) + ')'; }
    function mod(a, n) { return ((a % n) + n) % n; }
    // Smooth value noise on a ring of `period` cells (x in cells).
    function vnoiseP(s, x, period) {
        var i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
        var a = ih(s, mod(i, period), 17), b = ih(s, mod(i + 1, period), 17);
        return a + (b - a) * u;
    }
    function vnoise2(s, x, y) {
        var ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy;
        var ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
        var a = ih(s, ix, iy), b = ih(s, ix + 1, iy), c = ih(s, ix, iy + 1), d = ih(s, ix + 1, iy + 1);
        return (a + (b - a) * ux) * (1 - uy) + (c + (d - c) * ux) * uy;
    }
    // Organic outline noise around a closed shape, in [-0.5, 0.5].
    var RING_F = [4, 9, 19, 41], RING_A = [0.5, 0.27, 0.15, 0.08];
    function ring(s, a) {
        var v = 0;
        for (var k = 0; k < 4; k++) v += RING_A[k] * vnoiseP(s + k * 101, a * RING_F[k], RING_F[k]);
        return v - 0.5;
    }

    // ------------------------------------------------------------------
    // SVG: the two reveal masks and the filters
    // ------------------------------------------------------------------
    function maskDef(which, base, ink) {
        return '<mask id="xv-m-' + which + '" maskUnits="objectBoundingBox" maskContentUnits="objectBoundingBox"'
            + ' x="0" y="0" width="1" height="1" style="mask-type:luminance">'
            + '<g transform="scale(' + (1 / W).toFixed(10) + ',' + (1 / H).toFixed(10) + ')">'
            + '<rect x="0" y="0" width="' + W + '" height="' + H + '" fill="' + base + '"/>'
            + '<path id="xv-mp-' + which + '" fill="' + ink + '" fill-rule="nonzero" d=""/>'
            + '</g></mask>';
    }
    function ensureSvg() {
        if (svgReady && document.getElementById('xv-fx-svg')) return;
        if (document.getElementById('xv-fx-svg')) { svgReady = true; return; }
        if (!document.body) return;
        var svg = document.createElementNS(SVGNS, 'svg');
        svg.id = 'xv-fx-svg';
        svg.setAttribute('aria-hidden', 'true');
        svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
        svg.innerHTML = ''
            + maskDef('inn', '#000', '#fff')
            + maskDef('out', '#fff', '#000')
            // Warp: three displacements of one moving noise field, one per
            // colour channel, so the bend leaves rainbow fringes.
            + '<filter id="xv-warp" x="-10%" y="-10%" width="120%" height="120%" color-interpolation-filters="sRGB">'
            + '<feTurbulence id="xv-warp-turb" type="fractalNoise" baseFrequency="0.005 0.01" numOctaves="2" seed="3" result="noise"/>'
            + '<feOffset id="xv-warp-off" in="noise" dx="0" dy="0" result="n2"/>'
            + '<feDisplacementMap id="xv-warp-r" in="SourceGraphic" in2="n2" scale="0" xChannelSelector="R" yChannelSelector="G" result="dr"/>'
            + '<feDisplacementMap id="xv-warp-g" in="SourceGraphic" in2="n2" scale="0" xChannelSelector="R" yChannelSelector="G" result="dg"/>'
            + '<feDisplacementMap id="xv-warp-b" in="SourceGraphic" in2="n2" scale="0" xChannelSelector="R" yChannelSelector="G" result="db"/>'
            + '<feColorMatrix in="dr" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r"/>'
            + '<feColorMatrix in="dg" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g"/>'
            + '<feColorMatrix in="db" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b"/>'
            + '<feComposite in="r" in2="g" operator="arithmetic" k1="0" k2="1" k3="1" k4="0" result="rg"/>'
            + '<feComposite in="rg" in2="b" operator="arithmetic" k1="0" k2="1" k3="1" k4="0"/>'
            + '</filter>'
            // Glitch: noise that only varies down the frame, cut into steps,
            // shifts whole slices sideways. Red is shifted further than
            // green/blue, so each torn slice has an RGB split.
            + '<filter id="xv-glitch" x="-8%" y="-2%" width="116%" height="104%" color-interpolation-filters="sRGB">'
            + '<feTurbulence id="xv-gl-turb" type="fractalNoise" baseFrequency="0 0.04" numOctaves="1" seed="1" result="nb"/>'
            + '<feColorMatrix in="nb" type="matrix" values="1 0 0 0 0  0 0 0 0 0.5  0 0 0 0 0  0 0 0 0 1" result="nb1"/>'
            + '<feComponentTransfer in="nb1" result="map"><feFuncR id="xv-gl-tab" type="discrete" tableValues="0.5"/></feComponentTransfer>'
            + '<feDisplacementMap id="xv-gl-d1" in="SourceGraphic" in2="map" scale="0" xChannelSelector="R" yChannelSelector="G" result="d1"/>'
            + '<feDisplacementMap id="xv-gl-d2" in="SourceGraphic" in2="map" scale="0" xChannelSelector="R" yChannelSelector="G" result="d2"/>'
            + '<feOffset id="xv-gl-off" in="d2" dx="0" dy="0" result="d2o"/>'
            + '<feColorMatrix in="d2o" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r"/>'
            + '<feColorMatrix in="d1" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 1 0" result="gb"/>'
            + '<feComposite in="r" in2="gb" operator="arithmetic" k1="0" k2="1" k3="1" k4="0"/>'
            + '</filter>'
            + '<filter id="xv-blur" x="-8%" y="-4%" width="116%" height="108%">'
            + '<feGaussianBlur id="xv-blur-amt" stdDeviation="0 0"/>'
            + '</filter>';
        document.body.appendChild(svg);
        maskPaths = null;
        svgReady = true;
    }
    function attr(id, name, value) {
        var node = document.getElementById(id);
        if (node && node.getAttribute(name) !== value) node.setAttribute(name, value);
    }
    var region = { d: null, rule: null };
    function setRegion(d, rule) {
        ensureSvg();
        if (!maskPaths) {
            var a = document.getElementById('xv-mp-inn'), b = document.getElementById('xv-mp-out');
            if (!a || !b) return;
            maskPaths = [a, b];
        }
        if (region.d === d && region.rule === rule) return;
        region.d = d;
        region.rule = rule;
        for (var i = 0; i < 2; i++) {
            maskPaths[i].setAttribute('d', d || '');
            maskPaths[i].setAttribute('fill-rule', rule || 'nonzero');
        }
    }
    function setMask(el, which) {
        var m = which ? 'url(#xv-m-' + which + ')' : 'none';
        el.style.webkitMaskImage = m;
        el.style.maskImage = m;
        el.style.maskMode = which ? 'luminance' : '';
        el.style.webkitMaskSize = '';
        el.style.maskSize = '';
        el.style.webkitMaskRepeat = '';
        el.style.maskRepeat = '';
        el.style.webkitMaskPosition = '';
        el.style.maskPosition = '';
    }
    function clearEl(el) {
        if (!el) return;
        setMask(el, '');
        el.style.filter = '';
        el.style.opacity = '';
        el.style.transform = '';
    }

    function fxCanvas() {
        var c = document.getElementById('fx');
        if (!c) {
            var stage = document.getElementById('stage');
            if (!stage) return null;
            c = document.createElement('canvas');
            c.id = 'fx';
            c.width = W;
            c.height = H;
            stage.appendChild(c);
        }
        return c;
    }
    var mainDirty = true;
    function overlayCtx(blend, use, res) {
        var c = fxCanvas();
        if (!c) return null;
        var k = (window.devicePixelRatio || 1) * (res || 1);
        if (c.width !== Math.round(W * k) || c.height !== Math.round(H * k)) {
            c.width = Math.round(W * k);
            c.height = Math.round(H * k);
        }
        if (c.style.mixBlendMode !== (blend || '')) c.style.mixBlendMode = blend || '';
        if (!c.style.width) { c.style.width = W + 'px'; c.style.height = H + 'px'; }
        var ctx = c.getContext('2d');
        ctx.setTransform(k, 0, 0, k, 0, 0);
        if (mainDirty) ctx.clearRect(0, 0, W, H);
        mainDirty = !!use;
        ctx.globalCompositeOperation = 'source-over';
        ctx.globalAlpha = 1;
        return ctx;
    }
    // Big soft light (blooms, leaks, flashes) goes on a canvas at a third of
    // the resolution, scaled up. It looks the same and costs a ninth.
    var SOFT_K = 3;
    function softCanvas() {
        var c = document.getElementById('fx-soft');
        if (!c) {
            var stage = document.getElementById('stage');
            if (!stage) return null;
            c = document.createElement('canvas');
            c.id = 'fx-soft';
            c.style.cssText = 'position:absolute;left:0;top:0;width:' + W + 'px;height:' + H + 'px;z-index:940;pointer-events:none;display:none';
            var main = fxCanvas();
            if (main && main.parentNode === stage) stage.insertBefore(c, main); else stage.appendChild(c);
        }
        return c;
    }
    function softCtx(blend, use) {
        var c = softCanvas();
        if (!c) return null;
        if (!use) {
            if (c.style.display !== 'none') {
                c.getContext('2d').clearRect(0, 0, c.width, c.height);
                c.style.display = 'none';
            }
            return null;
        }
        var k = (window.devicePixelRatio || 1) / SOFT_K;
        if (c.width !== Math.round(W * k) || c.height !== Math.round(H * k)) {
            c.width = Math.round(W * k);
            c.height = Math.round(H * k);
        }
        c.style.display = '';
        if (c.style.mixBlendMode !== (blend || '')) c.style.mixBlendMode = blend || '';
        var ctx = c.getContext('2d');
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.clearRect(0, 0, W, H);
        ctx.globalCompositeOperation = 'source-over';
        ctx.globalAlpha = 1;
        return ctx;
    }
    function radial(ctx, x, y, r, stops) {
        var gr = ctx.createRadialGradient(x, y, 0, x, y, r);
        for (var i = 0; i < stops.length; i++) gr.addColorStop(stops[i][0], stops[i][1]);
        ctx.fillStyle = gr;
        var x0 = Math.max(0, x - r), y0 = Math.max(0, y - r);
        var x1 = Math.min(W, x + r), y1 = Math.min(H, y + r);
        if (x1 > x0 && y1 > y0) ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    }

    // Film grain / paper tooth: one 256 px tile made once, drawn shifted.
    var grainTile = null;
    function grain() {
        if (grainTile) return grainTile;
        var c = document.createElement('canvas');
        c.width = 256; c.height = 256;
        var g = c.getContext('2d');
        var img = g.createImageData(256, 256), d = img.data;
        // Sparse specks, not noise on every pixel: it reads as grain, and
        // the captured PNG frames stay quick to encode.
        for (var y = 0; y < 256; y++) {
            for (var x = 0; x < 256; x++) {
                var v = ih(911, x, y), i = (y * 256 + x) * 4;
                if (v > 0.018 && v < 0.982) continue;
                d[i] = d[i + 1] = d[i + 2] = v > 0.5 ? 255 : 0;
                d[i + 3] = Math.round(120 + 135 * ih(912, x, y));
            }
        }
        g.putImageData(img, 0, 0);
        grainTile = c;
        return c;
    }
    // Grain for light (the light leak): dense warm specks of every strength,
    // so a soft glow reads as exposed film, not a clean gradient.
    var lightGrainTile = null;
    function lightGrain() {
        if (lightGrainTile) return lightGrainTile;
        var c = document.createElement('canvas');
        c.width = 256; c.height = 256;
        var g = c.getContext('2d');
        var img = g.createImageData(256, 256), d = img.data;
        for (var y = 0; y < 256; y++) {
            for (var x = 0; x < 256; x++) {
                var v = ih(913, x, y), i = (y * 256 + x) * 4;
                if (v < 0.5) continue;
                d[i] = 255; d[i + 1] = 236; d[i + 2] = 214;
                d[i + 3] = Math.round(255 * Math.pow((v - 0.5) / 0.5, 1.6));
            }
        }
        g.putImageData(img, 0, 0);
        lightGrainTile = c;
        return c;
    }
    var grainScaled = {};
    function grainAt(n, kind) {
        var key = (kind || '') + n;
        if (grainScaled[key]) return grainScaled[key];
        var c = document.createElement('canvas');
        c.width = n; c.height = n;
        c.getContext('2d').drawImage(kind === 'light' ? lightGrain() : grain(), 0, 0, n, n);
        grainScaled[key] = c;
        return c;
    }
    // Soft light that falls off as (1 - t²)²: smooth all the way to zero,
    // so no glow or streak shows the edge of its shape.
    var SOFT_FALL = [[0, 1], [0.2, 0.922], [0.4, 0.706], [0.6, 0.41], [0.8, 0.13], [1, 0]];
    function softSpot(ctx, x, y, rx, ry, rot, rgb, a) {
        if (a < 0.004 || rx < 1 || ry < 1) return;
        ctx.save();
        ctx.translate(x, y);
        if (rot) ctx.rotate(rot);
        ctx.scale(rx / 100, ry / 100);
        var gr = ctx.createRadialGradient(0, 0, 0, 0, 0, 100);
        for (var i = 0; i < SOFT_FALL.length; i++) gr.addColorStop(SOFT_FALL[i][0], rgba(rgb, a * SOFT_FALL[i][1]));
        ctx.fillStyle = gr;
        ctx.fillRect(-100, -100, 200, 200);
        ctx.restore();
    }
    var patterns = { ctx: null };
    function patternOf(ctx, key, source) {
        if (patterns.ctx !== ctx) patterns = { ctx: ctx };
        if (!patterns[key]) patterns[key] = ctx.createPattern(source, 'repeat');
        return patterns[key];
    }
    // Grain is blitted as whole tiles in device pixels: no resampling per
    // pixel, which is what makes a scaled pattern fill slow.
    function drawGrain(ctx, alpha, step, scale, box, kind) {
        if (alpha < 0.005) return;
        var m = ctx.getTransform ? ctx.getTransform() : { a: 1 };
        var k = m.a || 1;
        var n = Math.max(32, Math.round(256 * (scale || 1.5) * k));
        var tile = grainAt(n, kind);
        var x0 = (box ? Math.max(0, box[0]) : 0) * k, y0 = (box ? Math.max(0, box[1]) : 0) * k;
        var x1 = (box ? Math.min(W, box[2]) : W) * k, y1 = (box ? Math.min(H, box[3]) : H) * k;
        if (x1 <= x0 || y1 <= y0) return;
        var ox = Math.floor(ih(5, step, 1) * n), oy = Math.floor(ih(5, step, 2) * n);
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.globalAlpha = clamp(alpha, 0, 1);
        var sx = Math.floor((x0 + ox) / n) * n - ox, sy = Math.floor((y0 + oy) / n) * n - oy;
        for (var y = sy; y < y1; y += n) {
            for (var x = sx; x < x1; x += n) ctx.drawImage(tile, x, y);
        }
        ctx.restore();
    }
    var scanTile = null;
    function drawScanlines(ctx, alpha, step) {
        if (!scanTile) {
            scanTile = document.createElement('canvas');
            scanTile.width = 4; scanTile.height = 3;
            var sg = scanTile.getContext('2d');
            sg.fillStyle = '#000';
            sg.fillRect(0, 2, 4, 1);
        }
        var pat = patternOf(ctx, 'scan', scanTile);
        ctx.save();
        ctx.globalAlpha = clamp(alpha, 0, 1);
        ctx.translate(0, step % 3);
        ctx.fillStyle = pat;
        ctx.fillRect(0, -3, W, H + 3);
        ctx.restore();
    }

    function polyD(pts) {
        var s = 'M' + pts[0].toFixed(1) + ' ' + pts[1].toFixed(1);
        for (var i = 2; i < pts.length; i += 2) s += 'L' + pts[i].toFixed(1) + ' ' + pts[i + 1].toFixed(1);
        return s + 'Z';
    }
    function tracePoly(ctx, pts) {
        ctx.moveTo(pts[0], pts[1]);
        for (var i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i], pts[i + 1]);
        ctx.closePath();
    }

    // ------------------------------------------------------------------
    // Shapes. One per frame, shared by both masks and the overlay.
    // ------------------------------------------------------------------

    // Pixel: a quadtree of 8-64 px blocks. Each leaf has a reveal threshold:
    // a left-to-right sweep, bent by smooth noise, plus per-block jitter.
    var pixCache = { sn: null, roots: null };
    function pixelTree(sn) {
        if (pixCache.sn === sn) return pixCache.roots;
        var split = { 64: 0.9, 32: 0.7, 16: 0.46 };
        function node(x, y, s) {
            var n = { x: x, y: y, s: s, kids: null, lo: 0, hi: 0, th: 0 };
            if (s > 8 && ih(sn ^ (s * 7919), x * 7 + 3, y * 13 + 5) < split[s]) {
                var h = s / 2;
                n.kids = [node(x, y, h), node(x + h, y, h), node(x, y + h, h), node(x + h, y + h, h)];
                n.lo = Math.min(n.kids[0].lo, n.kids[1].lo, n.kids[2].lo, n.kids[3].lo);
                n.hi = Math.max(n.kids[0].hi, n.kids[1].hi, n.kids[2].hi, n.kids[3].hi);
            } else {
                var cx = x + s / 2, cy = y + s / 2;
                var sweep = (cx / W) * 0.74 + (cy / H) * 0.26;
                var wob = vnoise2(sn + 3, cx / 300, cy / 300) - 0.5;
                n.th = clamp((0.56 * sweep + 0.16 * wob + 0.36 * ih(sn, x, y) + 0.08) / 1.0, 0, 1);
                n.lo = n.hi = n.th;
            }
            return n;
        }
        var roots = [];
        for (var y = 0; y < H; y += 64) for (var x = 0; x < W; x += 64) roots.push(node(x, y, 64));
        pixCache = { sn: sn, roots: roots };
        return roots;
    }
    function pixelE(p) { return -0.03 + 1.06 * (0.25 * p + 0.75 * smooth(p)); }
    function emitPix(nodes, e, out) {
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            if (n.hi < e) out.push('M' + n.x + ' ' + n.y + 'h' + n.s + 'v' + n.s + 'h-' + n.s + 'z');
            else if (n.lo >= e) continue;
            else if (n.kids) emitPix(n.kids, e, out);
        }
    }
    function visitPix(nodes, a, b, cb) {
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            if (n.hi < a || n.lo >= b) continue;
            if (n.kids) visitPix(n.kids, a, b, cb);
            else cb(n);
        }
    }

    // Film burn: one star-shaped hole that boils as it grows from an
    // ignition point. Star-shaped, so the outgoing mask is a clean cut-out.
    function burnShape(sn, p) {
        var p0 = 0.07, q = clamp((p - p0) / (1 - p0), 0, 1);
        var R = p < p0 ? 4 + 30 * (p / p0) : 34 + 2900 * Math.pow(q, 2.1);
        var cx = W * (0.30 + 0.40 * ih(sn, 1, 1)), cy = H * (0.28 + 0.44 * ih(sn, 2, 1));
        var N = 260, pts = new Array(N * 2), rs = new Array(N), ang = new Array(N);
        var tk = q * 3.2, k0 = Math.floor(tk), fr = smooth(tk - k0);
        for (var i = 0; i < N; i++) {
            var a = i / N;
            var n0 = ring(sn + k0 * 7919, a), n1 = ring(sn + (k0 + 1) * 7919, a);
            var n = n0 + (n1 - n0) * fr;
            var jag = (ih(sn, i, 77) - 0.5) * (4 + 0.006 * R) + (vnoiseP(sn + 9, a * 97, 97) - 0.5) * (10 + 0.025 * R);
            var r = Math.max(2, R * (1 + 0.8 * n) + jag);
            var th = a * TAU;
            rs[i] = r; ang[i] = th;
            pts[2 * i] = cx + Math.cos(th) * r;
            pts[2 * i + 1] = cy + Math.sin(th) * r;
        }
        return { cx: cx, cy: cy, R: R, q: q, rs: rs, ang: ang, pts: pts, N: N };
    }
    function burnRing(b, off, sn, wob) {
        var pts = new Array(b.N * 2);
        for (var i = 0; i < b.N; i++) {
            var r = b.rs[i] + off * (1 + wob * (vnoiseP(sn + 31, i / b.N * 23, 23) - 0.5) * 2);
            pts[2 * i] = b.cx + Math.cos(b.ang[i]) * r;
            pts[2 * i + 1] = b.cy + Math.sin(b.ang[i]) * r;
        }
        return pts;
    }

    // Ink bleed: five blots that bloom at different moments, with pointed
    // tendrils, and splatter drops thrown ahead of the edge.
    var INK_AT = [[0.26, 0.34], [0.70, 0.28], [0.40, 0.74], [0.80, 0.72], [0.55, 0.50]];
    var INK_DELAY = [0, 0.09, 0.16, 0.23, 0.30];
    function inkShapes(sn, p) {
        var blots = [];
        var order = [0, 1, 2, 3, 4].sort(function (a, b) { return ih(sn, a, 5) - ih(sn, b, 5); });
        for (var k = 0; k < 5; k++) {
            var d = INK_DELAY[order.indexOf(k)];
            var g = clamp((p - d) / (0.86 - d), 0, 1);
            if (g <= 0) continue;
            var cx = W * (INK_AT[k][0] + (ih(sn, k, 1) - 0.5) * 0.10);
            var cy = H * (INK_AT[k][1] + (ih(sn, k, 2) - 0.5) * 0.10);
            var R = 1350 * (0.35 * g + 0.65 * Math.pow(g, 1.9));
            var s = sn + k * 1013;
            var N = 300, pts = new Array(N * 2), rs = new Array(N);
            var tk = g * 2.2, k0 = Math.floor(tk), fr = smooth(tk - k0);
            var tendrils = [];
            for (var t = 0; t < 16; t++) {
                tendrils.push([ih(s, t, 3), 0.006 + 0.016 * ih(s, t, 4), (0.04 + 0.16 * ih(s, t, 6)) * Math.min(1, g * 1.8)]);
            }
            for (var i = 0; i < N; i++) {
                var a = i / N;
                var n0 = ring(s + k0 * 557, a), n1 = ring(s + (k0 + 1) * 557, a);
                var n = n0 + (n1 - n0) * fr;
                var r = R * (1 + 0.56 * n) + (vnoiseP(s + 7, a * 113, 113) - 0.5) * (8 + 0.05 * R)
                    + (vnoiseP(s + 8, a * 211, 211) - 0.5) * (4 + 0.02 * R);
                for (var j = 0; j < tendrils.length; j++) {
                    var dt = Math.abs(a - tendrils[j][0]);
                    if (dt > 0.5) dt = 1 - dt;
                    if (dt < tendrils[j][1] * 6) r += R * tendrils[j][2] * Math.exp(-dt / tendrils[j][1]);
                }
                rs[i] = r;
                pts[2 * i] = cx + Math.cos(a * TAU) * r;
                pts[2 * i + 1] = cy + Math.sin(a * TAU) * r;
            }
            var drops = [];
            for (var q = 0; q < 14; q++) {
                var g0 = 0.04 + 0.4 * ih(s, q, 8);
                if (g < g0) continue;
                var phi = ih(s, q, 9) * TAU, dist = 120 + 900 * ih(s, q, 10);
                if (dist < R * 0.72) continue;    // swallowed by the blot
                var rad = (3 + 22 * Math.pow(ih(s, q, 11), 2)) * Math.min(1, (g - g0) * 6);
                drops.push([cx + Math.cos(phi) * dist, cy + Math.sin(phi) * dist, rad]);
            }
            blots.push({ k: k, s: s, g: g, cx: cx, cy: cy, R: R, pts: pts, rs: rs, N: N, drops: drops });
        }
        return blots;
    }
    function circleD(x, y, r) {
        var s = '';
        for (var i = 0; i < 14; i++) {
            var a = i / 14 * TAU;
            s += (i ? 'L' : 'M') + (x + Math.cos(a) * r).toFixed(1) + ' ' + (y + Math.sin(a) * r).toFixed(1);
        }
        return s + 'Z';
    }

    // Glitch: a swipe from left to right with a ragged, blocky front. The
    // frame is cut into rows of squares and short bars. Each cell has its own
    // lead, so most of the new slide arrives as scattered squares and small
    // rectangles just ahead of the front, a few far ahead, and a few cells of
    // the old slide hang on just behind it. Cells near their switch point
    // flicker, and a row sometimes slips sideways for a frame.
    var GL_Z = 440;   // depth of the blocky front, px
    var glitchCache = { sn: null, rows: null };
    function glitchCells(sn) {
        if (glitchCache.sn === sn) return glitchCache.rows;
        var SIZES = [12, 16, 20, 24, 24, 32, 32, 40, 48];
        var rows = [], y = 0, r = 0, k = 0;
        while (y < H) {
            var h = Math.min(SIZES[Math.floor(ih(sn, r, 1) * SIZES.length)], H - y);
            var cells = [], x = 0;
            while (x < W) {
                var u = ih(sn, k, 2);
                var m = u < 0.45 ? 1 : u < 0.7 ? 2 : u < 0.85 ? 3 : u < 0.95 ? 4 : 6;   // squares, then short bars
                var w = Math.min(h * m, W - x);
                var a = ih(sn, k, 3);
                var off = a < 0.82 ? GL_Z * Math.pow(a / 0.82, 2.2)           // arrives ahead of the front
                    : -0.45 * GL_Z * Math.pow((a - 0.82) / 0.18, 1.4);         // old slide hangs on behind it
                cells.push({ x: x, w: w, c: x + w / 2, off: off, k: k });
                x += w;
                k++;
            }
            rows.push({ y: y, h: h, r: r, cells: cells });
            y += h;
            r++;
        }
        glitchCache = { sn: sn, rows: rows };
        return rows;
    }
    function glitchStep(p) { return Math.floor(p * 26); }
    // Where the front is: off the left edge at the start, far enough past the
    // right edge at the end that every lagging cell has switched.
    function glitchFront(p) { return -GL_Z - 20 + (W + 1.5 * GL_Z + 40) * (0.45 * p + 0.55 * smooth(p)); }

    function strobeX(p) { return -150 + (W + 300) * (0.72 * p + 0.28 * smooth(p)); }

    var GEO = { key: '' };
    function geometry(fx) {
        var p = fx.p, amp = fx.amp || 1;
        var key = fx.style + '|' + fx.seed + '|' + p.toFixed(5) + '|' + amp;
        if (GEO.key === key) return GEO;
        var sn = strSeed(fx.seed + ':' + fx.style);
        var g = { key: key, sn: sn, d: '', rule: 'nonzero', cov: smooth(p), masked: true };
        var parts, i;
        if (fx.style === 'pixel') {
            parts = [];
            g.e = pixelE(p);
            emitPix(pixelTree(sn), g.e, parts);
            g.d = parts.join('');
            g.cov = clamp(g.e, 0, 1);
        } else if (fx.style === 'shatter') {
            g.x = strobeX(p);
            var x = clamp(g.x, 0, W);
            g.d = x > 0 ? 'M0 0H' + x.toFixed(1) + 'V' + H + 'H0Z' : '';
            g.cov = x / W;
        } else if (fx.style === 'burn') {
            g.burn = burnShape(sn, p);
            g.d = polyD(g.burn.pts);
            g.cov = clamp(Math.PI * Math.pow(g.burn.R * 0.85, 2) / (W * H), 0, 1);
        } else if (fx.style === 'paint') {
            g.blots = inkShapes(sn, p);
            parts = [];
            for (i = 0; i < g.blots.length; i++) {
                parts.push(polyD(g.blots[i].pts));
                for (var j = 0; j < g.blots[i].drops.length; j++) {
                    var dr = g.blots[i].drops[j];
                    if (dr[2] > 0.6) parts.push(circleD(dr[0], dr[1], dr[2]));
                }
            }
            g.d = parts.join('');
            g.cov = smooth(p / 0.82);
        } else if (fx.style === 'glitch') {
            var rows = glitchCells(sn), step = glitchStep(p), b = bell(p) * amp;
            var front = glitchFront(p), flick = 90 * b;
            parts = [];
            g.front = front;
            g.sparks = [];     // new-slide cells ahead of the front, for the overlay's tints
            for (i = 0; i < rows.length; i++) {
                var row = rows[i];
                var f = front;
                if (ih(sn, row.r, step + 900) > 0.93) f += (ih(sn, row.r, step + 950) - 0.5) * 360 * b;   // a row slips
                var run = -1;
                for (var j = 0; j < row.cells.length; j++) {
                    var cell = row.cells[j];
                    var dd = cell.c - (f + cell.off);
                    var on = dd < 0;
                    if (Math.abs(dd) < flick && ih(sn, cell.k, step + 500) > 0.5) on = !on;
                    if (on && run < 0) run = cell.x;
                    if (!on && run >= 0) {
                        parts.push('M' + run + ' ' + row.y + 'H' + cell.x + 'V' + (row.y + row.h) + 'H' + run + 'Z');
                        run = -1;
                    }
                    if (on && cell.c > f && g.sparks.length < 240) g.sparks.push([cell.x, row.y, cell.w, row.h, cell.k]);
                }
                if (run >= 0) parts.push('M' + run + ' ' + row.y + 'H' + W + 'V' + (row.y + row.h) + 'H' + run + 'Z');
            }
            g.d = parts.join('');
            g.cov = clamp((front + 0.3 * GL_Z) / W, 0, 1);
        } else {
            g.masked = false;
        }
        if (g.masked) setRegion(g.d, g.rule);
        GEO = g;
        return g;
    }

    // ------------------------------------------------------------------
    // Filters set per frame
    // ------------------------------------------------------------------
    function setWarp(scale, p) {
        ensureSvg();
        attr('xv-warp-turb', 'baseFrequency', (0.0042 + 0.0016 * Math.sin(p * 3.1)).toFixed(5) + ' '
            + (0.0085 + 0.0025 * Math.cos(p * 2.3)).toFixed(5));
        attr('xv-warp-off', 'dx', ((p - 0.5) * 260).toFixed(1));
        attr('xv-warp-off', 'dy', ((0.5 - p) * 200).toFixed(1));
        attr('xv-warp-r', 'scale', (scale * 1.32).toFixed(2));
        attr('xv-warp-g', 'scale', scale.toFixed(2));
        attr('xv-warp-b', 'scale', (scale * 0.72).toFixed(2));
    }
    function setGlitch(sn, p, burst) {
        ensureSvg();
        var step = glitchStep(p);
        attr('xv-gl-turb', 'seed', String(1 + mod(sn + step * 13, 997)));
        attr('xv-gl-turb', 'baseFrequency', '0 ' + (0.012 + 0.05 * ih(sn, step, 2)).toFixed(4));
        var tv = [];
        for (var i = 0; i < 24; i++) {
            var h = ih(sn, step * 31 + i, 3);
            tv.push(h < 0.5 ? '0.5' : ih(sn, step * 31 + i, 4).toFixed(3));
        }
        attr('xv-gl-tab', 'tableValues', tv.join(' '));
        var s1 = 150 * burst;
        attr('xv-gl-d1', 'scale', s1.toFixed(1));
        attr('xv-gl-d2', 'scale', (s1 * 1.4).toFixed(1));
        var side = ih(sn, step, 6) > 0.5 ? 1 : -1;
        attr('xv-gl-off', 'dx', (side * (6 + 22 * ih(sn, step, 7)) * burst).toFixed(1));
        attr('xv-gl-off', 'dy', ((ih(sn, step, 8) - 0.5) * 6 * burst).toFixed(1));
    }
    function setBlur(x) {
        ensureSvg();
        attr('xv-blur-amt', 'stdDeviation', x.toFixed(2) + ' 0.15');
    }

    // ------------------------------------------------------------------
    // Slides
    // ------------------------------------------------------------------
    function paint(slide, fx) {
        var el = slide.el;
        var incoming = slide === fx.inn;
        var p = fx.p, amp = fx.amp || 1;
        if (!fx.seed) fx.seed = (fx.inn && fx.inn.el && fx.inn.el.id) || 'fx';
        el.style.filter = '';
        setMask(el, '');
        el.style.transform = '';
        if (p > 0.985) {
            // The new slide is whole; the old one is gone (no last-frame flash).
            el.style.opacity = incoming ? '' : '0';
            return incoming ? 1 : 0;
        }
        var g = geometry(fx);
        var o = 1, shown = 1;
        var sm = smooth(p);
        if (g.masked) {
            setMask(el, incoming ? 'inn' : 'out');
            o = incoming ? g.cov : 1 - g.cov;
        }
        if (fx.style === 'glitch') {
            // The old slide holds still while the swipe crosses it. The new
            // one arrives torn (RGB split, slices shoved sideways) and settles
            // as the swipe finishes.
            if (incoming) {
                var step = glitchStep(p);
                var burst = amp * Math.pow(clamp(1 - p / 0.82, 0, 1), 0.7) * (0.5 + 0.5 * ih(g.sn, step, 1));
                if (burst > 0.04 && ih(g.sn, step, 13) > 0.25) {
                    setGlitch(g.sn, p, burst);
                    el.style.filter = 'url(#xv-glitch)';
                    var jx = (ih(g.sn, step, 11) - 0.5) * 30 * burst;
                    el.style.transform = 'translateX(' + jx.toFixed(2) + 'px)';
                }
            }
        } else if (fx.style === 'burn') {
            if (!incoming) {
                // The old frame heats: browner, then brighter near the end.
                var heat = smooth(p / 0.7);
                el.style.filter = 'sepia(' + (0.55 * heat).toFixed(3) + ') saturate(' + (1 + 0.5 * heat).toFixed(3)
                    + ') brightness(' + (1 + 0.12 * heat).toFixed(3) + ')';
            } else if (p < 0.45) {
                el.style.filter = 'brightness(' + (1 + 0.35 * (1 - p / 0.45)).toFixed(3) + ')';
            }
        } else if (fx.style === 'paint') {
            if (incoming) el.style.filter = 'saturate(' + (1 + 0.25 * bell(p)).toFixed(3) + ')';
        } else if (fx.style === 'warp') {
            var sc = Math.pow(bell(p), 1.15) * 150 * amp;
            setWarp(sc, p);
            if (incoming) {
                shown = smooth((p - 0.26) / 0.44);
                el.style.transform = 'scale(' + (1.14 - 0.14 * sm).toFixed(4) + ') rotate(' + (-2.2 * (1 - sm) * amp).toFixed(3) + 'deg)';
            } else {
                shown = 1 - smooth((p - 0.30) / 0.44);
                el.style.transform = 'scale(' + (1 + 0.18 * sm * amp).toFixed(4) + ') rotate(' + (2.2 * sm * amp).toFixed(3) + 'deg)';
            }
            if (sc > 1 && shown > 0.02) el.style.filter = 'url(#xv-warp)';
            o = shown;
        } else if (fx.style === 'pixel') {
            // Mask only.
        } else if (fx.style === 'lightleak') {
            var blur = bell(p) * 7 * amp;
            setBlur(blur);
            var warm = bell(p) * amp;
            var lit = 1 + 0.28 * warm + 0.3 * leakFlash(p) * amp;
            el.style.filter = (blur > 0.4 ? 'url(#xv-blur) ' : '') + 'brightness(' + lit.toFixed(3)
                + ') sepia(' + (0.22 * warm).toFixed(3) + ')';
            // The swap is tighter than before and sits under the flash.
            if (incoming) {
                shown = smooth((p - 0.36) / 0.24);
                el.style.transform = 'translateX(' + ((1 - sm) * 90 * amp).toFixed(2) + 'px) scale(' + (1.06 - 0.06 * sm).toFixed(4) + ')';
            } else {
                shown = 1 - smooth((p - 0.30) / 0.24);
                el.style.transform = 'translateX(' + (-sm * 120 * amp).toFixed(2) + 'px) scale(' + (1 + 0.03 * sm).toFixed(4) + ')';
            }
            o = shown;
        } else if (fx.style === 'shatter') {
            // Strobe wipe: mask only; the bar is on the overlay.
        }
        el.style.opacity = shown >= 0.999 ? '' : Math.max(0, shown).toFixed(3);
        return clamp(o, 0, 1);
    }

    // ------------------------------------------------------------------
    // Overlay drawings
    // ------------------------------------------------------------------
    function drawGlitch(ctx, fx, g) {
        var p = fx.p, amp = fx.amp || 1, sn = g.sn;
        var step = glitchStep(p);
        var b = bell(p) * amp, burst = b * (0.45 + 0.55 * ih(sn, step, 1));
        if (b < 0.02) return;
        var i, j, front = g.front || 0;
        // Everything below gathers around the front, so the marks travel with the swipe.
        var x0 = front - 0.35 * GL_Z, x1 = front + GL_Z;
        drawGrain(ctx, 0.7 * burst, step, 1, [x0, 0, x1, H]);
        drawScanlines(ctx, 0.12 * b, step);
        var cols = [RED, CYAN, [255, 255, 255], GOLD, [200, 80, 255]];
        // Some of the squares and bars that arrive early light up in a flat
        // colour, and some carry a red / cyan ghost knocked sideways.
        var sparks = g.sparks || [];
        for (i = 0; i < sparks.length; i++) {
            var s = sparks[i], hv = ih(sn, s[4], step + 700);
            if (hv < 0.55) continue;
            ctx.fillStyle = rgba(cols[Math.floor(ih(sn, s[4], step + 710) * 5)], (0.14 + 0.4 * (hv - 0.55) / 0.45) * burst);
            ctx.fillRect(s[0], s[1], s[2], s[3]);
            if (hv > 0.85) {
                var gd = (4 + 10 * ih(sn, s[4], step + 720)) * burst;
                ctx.fillStyle = rgba(RED, 0.35 * burst);
                ctx.fillRect(s[0] - gd, s[1], s[2], Math.max(1, s[3] * 0.5));
                ctx.fillStyle = rgba(CYAN, 0.35 * burst);
                ctx.fillRect(s[0] + gd, s[1] + s[3] * 0.5, s[2], Math.max(1, s[3] * 0.5));
            }
        }
        // Short RGB slices across the front.
        var n = 6 + Math.floor(12 * burst);
        for (i = 0; i < n; i++) {
            var sy = ih(sn, step * 41 + i, 2) * H, sh = 1 + Math.pow(ih(sn, step * 41 + i, 3), 3) * 22;
            var sx = front - 0.3 * GL_Z + ih(sn, step * 41 + i, 4) * 1.1 * GL_Z;
            var sw = 60 + Math.pow(ih(sn, step * 41 + i, 7), 1.5) * 380;
            ctx.fillStyle = rgba(cols[Math.floor(ih(sn, step * 41 + i, 5) * 5)], (0.12 + 0.3 * ih(sn, step * 41 + i, 6)) * burst);
            ctx.fillRect(sx - sw / 2, sy, sw, sh);
        }
        // Datamosh: macroblocks of flat colour with a smear trailing down, just ahead of the front.
        var m = 1 + Math.floor(3 * burst);
        for (i = 0; i < m; i++) {
            var bs = ih(sn, step * 53 + i, 1) > 0.5 ? 16 : 8;
            var gx = Math.floor((front + ih(sn, step * 53 + i, 2) * 0.8 * GL_Z) / 16) * 16;
            var gy = Math.floor(ih(sn, step * 53 + i, 3) * (H - 160) / 16) * 16;
            var cw = 4 + Math.floor(ih(sn, step * 53 + i, 4) * 16), ch = 2 + Math.floor(ih(sn, step * 53 + i, 5) * 6);
            var base = cols[Math.floor(ih(sn, step * 53 + i, 6) * 5)];
            for (var cy = 0; cy < ch; cy++) {
                for (var cx = 0; cx < cw; cx++) {
                    var hv = ih(sn + i, cx + step * 17, cy);
                    if (hv > 0.62) continue;
                    var tint = hv < 0.2 ? [12, 16, 26] : base;
                    ctx.fillStyle = rgba(tint, (0.16 + 0.5 * hv) * burst);
                    ctx.fillRect(gx + cx * bs, gy + cy * bs, bs, bs);
                }
            }
            var smear = ctx.createLinearGradient(0, gy + ch * bs, 0, gy + ch * bs + 140);
            smear.addColorStop(0, rgba(base, 0.22 * burst));
            smear.addColorStop(1, rgba(base, 0));
            ctx.fillStyle = smear;
            ctx.fillRect(gx, gy + ch * bs, cw * bs, 140);
        }
        // Noise bursts: clusters of specks of many sizes.
        var clusters = 2 + Math.floor(3 * burst);
        for (i = 0; i < clusters; i++) {
            var ox = front + (ih(sn, step * 61 + i, 1) - 0.2) * GL_Z, oy = ih(sn, step * 61 + i, 2) * H;
            for (j = 0; j < 60; j++) {
                var h1 = ih(sn + j, step * 61 + i, 3), h2 = ih(sn + j, step * 61 + i, 4), h3 = ih(sn + j, step * 61 + i, 5);
                var v = Math.round(150 + 105 * h3);
                ctx.fillStyle = 'rgba(' + v + ',' + v + ',' + v + ',' + ((0.25 + 0.55 * h3) * burst).toFixed(3) + ')';
                ctx.fillRect(ox + (h1 - 0.5) * 260, oy + (h2 - 0.5) * 70, 1 + Math.pow(h3, 2) * 12, 1 + h1 * 4);
            }
        }
        // Tear lines through the front.
        for (i = 0; i < 3; i++) {
            ctx.fillStyle = 'rgba(255,255,255,' + (0.55 * burst * ih(sn, step, 20 + i)).toFixed(3) + ')';
            ctx.fillRect(x0 - 200, ih(sn, step * 7 + i, 21) * H, x1 - x0 + 400, 1.5);
        }
        if (ih(sn, step, 9) > 0.88) {
            ctx.fillStyle = rgba(ih(sn, step, 10) > 0.5 ? CYAN : [255, 60, 200], 0.05 * burst);
            ctx.fillRect(0, 0, W, H);
        }
    }

    function traceInk(ctx, blots) {
        for (var k = 0; k < blots.length; k++) {
            tracePoly(ctx, blots[k].pts);
            for (var q = 0; q < blots[k].drops.length; q++) {
                var dr = blots[k].drops[q];
                if (dr[2] < 0.6) continue;
                ctx.moveTo(dr[0] + dr[2], dr[1]);
                ctx.arc(dr[0], dr[1], dr[2], 0, TAU);
            }
        }
    }
    function insideOther(blots, k, x, y) {
        for (var j = 0; j < blots.length; j++) {
            if (j === k) continue;
            var o = blots[j];
            var dx = x - o.cx, dy = y - o.cy;
            var a = Math.atan2(dy, dx) / TAU;
            if (a < 0) a += 1;
            var r = o.rs[Math.round(a * o.N) % o.N];
            if (dx * dx + dy * dy < (r - 3) * (r - 3)) return true;
        }
        return false;
    }
    function drawInk(ctx, fx, g) {
        var p = fx.p, amp = fx.amp || 1, sn = g.sn;
        var fade = 1 - smooth((p - 0.72) / 0.26);
        if (fade <= 0.01 || !g.blots.length) return;
        var k, i;
        var box = [W, H, 0, 0];
        for (k = 0; k < g.blots.length; k++) {
            var pb = g.blots[k].pts;
            for (i = 0; i < pb.length; i += 2) {
                if (pb[i] < box[0]) box[0] = pb[i];
                if (pb[i] > box[2]) box[2] = pb[i];
                if (pb[i + 1] < box[1]) box[1] = pb[i + 1];
                if (pb[i + 1] > box[3]) box[3] = pb[i + 1];
            }
        }
        box = [Math.max(0, box[0] - 40), Math.max(0, box[1] - 40), Math.min(W, box[2] + 40), Math.min(H, box[3] + 40)];
        // 1. The ink itself: it floods in just ahead of the new slide and
        //    clears behind the front, so a band of wet indigo leads the reveal.
        ctx.save();
        ctx.beginPath();
        traceInk(ctx, g.blots);
        ctx.fillStyle = 'rgba(14,19,70,' + (0.94 * amp).toFixed(3) + ')';
        ctx.fill();
        ctx.globalCompositeOperation = 'source-atop';
        for (k = 0; k < g.blots.length; k++) {
            var bl0 = g.blots[k];
            radial(ctx, bl0.cx, bl0.cy, bl0.R * 1.3, [[0, 'rgba(78,112,246,0.75)'], [0.3, 'rgba(78,112,246,0.75)'],
                [0.78, 'rgba(46,70,200,0.32)'], [1, 'rgba(46,70,200,0)']]);
        }
        drawGrain(ctx, 0.6, 11, 1.25, box);   // pigment texture inside the wet band
        ctx.globalCompositeOperation = 'destination-out';
        var lags = [[0.02, 0.22], [0.04, 0.28], [0.065, 0.36], [0.09, 0.48], [0.12, 0.66], [0.16, 1]];
        for (i = 0; i < lags.length; i++) {
            var back = inkShapes(sn, p - lags[i][0]);
            if (!back.length) break;
            ctx.beginPath();
            traceInk(ctx, back);
            ctx.fillStyle = 'rgba(0,0,0,' + lags[i][1] + ')';
            ctx.fill();
        }
        ctx.restore();
        // 2. The outer edge of all the blots together: a dark pigment rim,
        //    a soft halo of wet paper, and a bright wet line just inside.
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        for (k = 0; k < g.blots.length; k++) {
            var bl = g.blots[k];
            var e = Math.min(1, bl.g * 5) * fade * amp;
            if (e < 0.01) continue;
            var edgeOn = new Array(bl.N);
            for (i = 0; i < bl.N; i++) edgeOn[i] = !insideOther(g.blots, k, bl.pts[2 * i], bl.pts[2 * i + 1]);
            var tracer = function (off) {
                ctx.beginPath();
                var open = false;
                for (var j = 0; j <= bl.N; j++) {
                    var ii = j % bl.N;
                    if (!edgeOn[ii]) { open = false; continue; }
                    var a = ii / bl.N * TAU, r = Math.max(0, bl.rs[ii] + off);
                    var x = bl.cx + Math.cos(a) * r, y = bl.cy + Math.sin(a) * r;
                    if (open) ctx.lineTo(x, y); else { ctx.moveTo(x, y); open = true; }
                }
            };
            tracer(10);
            ctx.strokeStyle = 'rgba(40,64,190,' + (0.20 * e).toFixed(3) + ')';
            ctx.lineWidth = 26;
            ctx.stroke();
            tracer(0);
            ctx.strokeStyle = 'rgba(10,14,58,' + (0.9 * e).toFixed(3) + ')';
            ctx.lineWidth = 5;
            ctx.stroke();
            tracer(-7);
            ctx.strokeStyle = 'rgba(150,182,255,' + (0.38 * e).toFixed(3) + ')';
            ctx.lineWidth = 1.6;
            ctx.stroke();
            // Capillary fibres feathering out of the edge into the paper.
            ctx.beginPath();
            for (var f = 0; f < 150; f++) {
                var idx = Math.floor(ih(bl.s, f, 1) * bl.N);
                if (!edgeOn[idx]) continue;
                var aa = idx / bl.N * TAU;
                var turn = (ih(bl.s, f, 2) - 0.5) * 1.2, len = (5 + 30 * Math.pow(ih(bl.s, f, 3), 2)) * Math.min(1, bl.g * 3);
                var ex = bl.pts[2 * idx], ey = bl.pts[2 * idx + 1];
                ctx.moveTo(ex, ey);
                ctx.quadraticCurveTo(ex + Math.cos(aa) * len * 0.5, ey + Math.sin(aa) * len * 0.5,
                    ex + Math.cos(aa + turn) * len, ey + Math.sin(aa + turn) * len);
            }
            ctx.strokeStyle = 'rgba(22,34,128,' + (0.6 * e).toFixed(3) + ')';
            ctx.lineWidth = 1.2;
            ctx.stroke();
            // Granulation: pigment specks settling just inside the rim.
            ctx.fillStyle = 'rgba(8,12,60,' + (0.55 * e).toFixed(3) + ')';
            for (var d = 0; d < 160; d++) {
                var id2 = Math.floor(ih(bl.s, d, 12) * bl.N);
                if (!edgeOn[id2]) continue;
                var a2 = id2 / bl.N * TAU, r2 = bl.rs[id2] - ih(bl.s, d, 13) * 40;
                var sz = 1 + ih(bl.s, d, 14) * 2.5;
                ctx.fillRect(bl.cx + Math.cos(a2) * r2, bl.cy + Math.sin(a2) * r2, sz, sz);
            }
            // Rims on the splatter drops.
            for (var q = 0; q < bl.drops.length; q++) {
                var dr = bl.drops[q];
                if (dr[2] < 0.6 || insideOther(g.blots, -1, dr[0], dr[1])) continue;
                ctx.beginPath();
                ctx.arc(dr[0], dr[1], dr[2], 0, TAU);
                ctx.strokeStyle = 'rgba(10,14,58,' + (0.85 * e).toFixed(3) + ')';
                ctx.lineWidth = Math.min(3, 1 + dr[2] * 0.2);
                ctx.stroke();
            }
        }
        drawGrain(ctx, 0.25 * bell(p) * amp, 3, 1.25, box);    // paper tooth
    }

    function strokeSegments(ctx, pts, N, seg, width, colorFn) {
        var per = Math.ceil(N / seg);
        for (var s = 0; s < seg; s++) {
            var a = s * per, b = Math.min(N, a + per + 1);
            ctx.beginPath();
            for (var i = a; i <= b; i++) {
                var k = i % N;
                if (i === a) ctx.moveTo(pts[2 * k], pts[2 * k + 1]); else ctx.lineTo(pts[2 * k], pts[2 * k + 1]);
            }
            ctx.strokeStyle = colorFn(s);
            ctx.lineWidth = width;
            ctx.stroke();
        }
    }
    function drawBurn(ctx, soft, fx, g) {
        var p = fx.p, amp = fx.amp || 1, sn = g.sn, b = g.burn;
        var film = Math.floor(p * 30);            // one "film frame" per video frame
        var flick = 0.72 + 0.28 * ih(sn, film, 1);
        var env = smooth(p / 0.05) * (1 - smooth((p - 0.9) / 0.09));
        // Warm, flickering film tint over the whole frame.
        soft.fillStyle = 'rgba(255,150,70,' + (0.07 * bell(p) * flick * amp).toFixed(3) + ')';
        soft.fillRect(0, 0, W, H);
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        var edge = clamp(b.q * 8, 0, 1) * env * amp;
        if (b.R > 3) {
            // Brown scorch, then a black char band, just outside the hole.
            ctx.beginPath();
            tracePoly(ctx, burnRing(b, 80, sn, 0.7));
            ctx.strokeStyle = 'rgba(70,34,10,' + (0.32 * edge).toFixed(3) + ')';
            ctx.lineWidth = 130;
            ctx.stroke();
            ctx.beginPath();
            tracePoly(ctx, burnRing(b, 34, sn, 0.6));
            ctx.strokeStyle = 'rgba(48,20,6,' + (0.55 * edge).toFixed(3) + ')';
            ctx.lineWidth = 46;
            ctx.stroke();
            ctx.beginPath();
            tracePoly(ctx, burnRing(b, 12, sn, 0.5));
            ctx.strokeStyle = 'rgba(14,6,2,' + (0.92 * edge).toFixed(3) + ')';
            ctx.lineWidth = 22;
            ctx.stroke();
            // A hot band just inside the edge: the frame behind the fresh
            // hole still glows, then cools.
            soft.save();
            soft.beginPath();
            tracePoly(soft, b.pts);
            soft.fillStyle = 'rgba(255,118,22,' + (0.62 * edge).toFixed(3) + ')';
            soft.fill();
            soft.globalCompositeOperation = 'destination-out';
            var cool = [[0.015, 0.45], [0.035, 0.6], [0.06, 1]];
            for (var c = 0; c < cool.length; c++) {
                if (p - cool[c][0] <= 0.07) break;
                soft.beginPath();
                tracePoly(soft, burnShape(sn, p - cool[c][0]).pts);
                soft.fillStyle = 'rgba(0,0,0,' + cool[c][1] + ')';
                soft.fill();
            }
            soft.restore();
            // Bubbling emulsion in the char band.
            for (var bb = 0; bb < 90; bb++) {
                var bi = Math.floor(ih(sn, bb, 80) * b.N);
                var br = b.rs[bi] + 10 + ih(sn, bb, 81) * 46;
                var bx = b.cx + Math.cos(b.ang[bi]) * br, by = b.cy + Math.sin(b.ang[bi]) * br;
                var bs = 2 + ih(sn, bb, 82) * 7;
                ctx.beginPath();
                ctx.arc(bx, by, bs, 0, TAU);
                ctx.fillStyle = 'rgba(30,12,3,' + (0.75 * edge).toFixed(3) + ')';
                ctx.fill();
                ctx.beginPath();
                ctx.arc(bx - bs * 0.3, by - bs * 0.3, bs * 0.45, 0, TAU);
                ctx.fillStyle = 'rgba(255,170,90,' + (0.35 * edge).toFixed(3) + ')';
                ctx.fill();
            }
            // Ember rim: glow, orange, yellow, white-hot core. Each stretch of
            // the edge flickers on its own.
            var rim = b.pts;
            var glowOf = function (k) { return 0.55 + 0.45 * vnoiseP(sn + 41, k * 1.7 + p * 30, 64); };
            strokeSegments(soft, burnRing(b, 4, sn, 0.3), b.N, 26, 34, function (k) {
                return 'rgba(255,90,10,' + (0.34 * edge * glowOf(k) * flick).toFixed(3) + ')';
            });
            strokeSegments(ctx, rim, b.N, 26, 12, function (k) {
                return 'rgba(255,128,24,' + (0.95 * edge * glowOf(k)).toFixed(3) + ')';
            });
            strokeSegments(ctx, rim, b.N, 26, 5, function (k) {
                return 'rgba(255,214,110,' + (edge * glowOf(k)).toFixed(3) + ')';
            });
            ctx.beginPath();
            tracePoly(ctx, rim);
            ctx.strokeStyle = 'rgba(255,250,232,' + (0.9 * edge * flick).toFixed(3) + ')';
            ctx.lineWidth = 1.6;
            ctx.stroke();
            // Pinholes burning through ahead of the edge.
            for (var h = 0; h < 9; h++) {
                var t0 = 0.08 + 0.55 * ih(sn, h, 30);
                if (p < t0) continue;
                var ang = ih(sn, h, 31) * TAU, dist = 260 + 1300 * ih(sn, h, 32);
                var idx = Math.round(ang / TAU * b.N) % b.N;
                if (b.rs[idx] > dist - 10) continue;     // the edge has reached it
                var px = b.cx + Math.cos(ang) * dist, py = b.cy + Math.sin(ang) * dist;
                var pr = 3 + 16 * smooth((p - t0) / 0.3) * (0.5 + 0.5 * ih(sn, h, 33));
                ctx.beginPath();
                ctx.arc(px, py, pr + 9, 0, TAU);
                ctx.fillStyle = 'rgba(40,16,4,' + (0.5 * env).toFixed(3) + ')';
                ctx.fill();
                ctx.beginPath();
                ctx.arc(px, py, pr, 0, TAU);
                ctx.fillStyle = 'rgba(255,140,30,' + (0.9 * env * flick).toFixed(3) + ')';
                ctx.fill();
                ctx.beginPath();
                ctx.arc(px, py, pr * 0.45, 0, TAU);
                ctx.fillStyle = 'rgba(255,248,220,' + (0.95 * env).toFixed(3) + ')';
                ctx.fill();
            }
            // Sparks thrown off the edge.
            ctx.lineWidth = 2.2;
            for (var s = 0; s < 80; s++) {
                var born = 0.06 + 0.84 * ih(sn, s, 40);
                var age = (p - born) / 0.16;
                if (age < 0 || age > 1) continue;
                var i2 = Math.floor(ih(sn, s, 41) * b.N);
                var dir = b.ang[i2] + (ih(sn, s, 42) - 0.5) * 0.9;
                var sp = 60 + 260 * ih(sn, s, 43);
                var ex = b.pts[2 * i2], ey = b.pts[2 * i2 + 1];
                var x1 = ex + Math.cos(dir) * sp * age, y1 = ey + Math.sin(dir) * sp * age - 90 * age * age;
                var x0 = x1 - Math.cos(dir) * (10 + sp * 0.08), y0 = y1 - Math.sin(dir) * (10 + sp * 0.08) + 6 * age;
                ctx.strokeStyle = 'rgba(255,' + Math.round(230 - 120 * age) + ',' + Math.round(150 - 130 * age) + ','
                    + ((1 - age) * 0.95 * env).toFixed(3) + ')';
                ctx.beginPath();
                ctx.moveTo(x0, y0);
                ctx.lineTo(x1, y1);
                ctx.stroke();
            }
        }
        // White-hot flash at ignition.
        if (p < 0.24) {
            var f = 1 - p / 0.24;
            var rad = 140 + 560 * (p / 0.24);
            radial(soft, b.cx, b.cy, rad, [[0, 'rgba(255,255,248,' + (0.98 * f).toFixed(3) + ')'],
                [0.22, 'rgba(255,232,160,' + (0.8 * f).toFixed(3) + ')'],
                [0.55, 'rgba(255,128,30,' + (0.35 * f).toFixed(3) + ')'], [1, 'rgba(255,80,0,0)']]);
            soft.fillStyle = 'rgba(255,236,200,' + (0.30 * f * f * amp).toFixed(3) + ')';
            soft.fillRect(0, 0, W, H);
        }
        // Film: grain, scratches, dust, an exposure flicker.
        drawGrain(ctx, 0.5 * env * amp, film, 1.5);    // film grain stays sharp
        for (var sc = 0; sc < 5; sc++) {
            if (ih(sn, film, 50 + sc) < 0.35) continue;
            var sx = ih(sn, film * 5 + sc, 51) * W;
            ctx.strokeStyle = sc % 2 ? 'rgba(255,240,220,' + (0.22 * env).toFixed(3) + ')' : 'rgba(0,0,0,' + (0.3 * env).toFixed(3) + ')';
            ctx.lineWidth = 1 + ih(sn, film, 52 + sc) * 1.5;
            ctx.beginPath();
            ctx.moveTo(sx, 0);
            ctx.bezierCurveTo(sx + 6, H * 0.3, sx - 6, H * 0.7, sx + 3, H);
            ctx.stroke();
        }
        for (var d = 0; d < 12; d++) {
            var dx = ih(sn, film * 12 + d, 60) * W, dy = ih(sn, film * 12 + d, 61) * H;
            ctx.fillStyle = ih(sn, d, film) > 0.5 ? 'rgba(10,6,2,' + (0.55 * env).toFixed(3) + ')' : 'rgba(255,245,230,' + (0.4 * env).toFixed(3) + ')';
            ctx.beginPath();
            ctx.ellipse(dx, dy, 1 + ih(sn, d, 62) * 4, 1 + ih(sn, d, 63) * 2.5, ih(sn, d, 64) * 3, 0, TAU);
            ctx.fill();
        }
        if (ih(sn, film, 70) > 0.7) {
            soft.fillStyle = 'rgba(255,240,215,' + (0.06 * env).toFixed(3) + ')';
            soft.fillRect(0, 0, W, H);
        }
    }

    function drawPixel(ctx, fx, g) {
        var amp = fx.amp || 1, e = g.e, sn = g.sn;
        var cols = [GOLD, BLUE, CYAN, [255, 255, 255]];
        visitPix(pixelTree(sn), e - 0.05, e + 0.03, function (n) {
            if (n.th < e) {
                var f = 1 - (e - n.th) / 0.05;
                ctx.fillStyle = 'rgba(255,250,235,' + (0.7 * f * amp).toFixed(3) + ')';
                ctx.fillRect(n.x, n.y, n.s, n.s);
            } else {
                var f2 = 1 - (n.th - e) / 0.03;
                ctx.fillStyle = rgba(cols[Math.floor(ih(sn, n.x, n.y + 1) * 4)], 0.5 * f2 * amp);
                ctx.fillRect(n.x + 1, n.y + 1, n.s - 2, n.s - 2);
            }
        });
    }

    function drawLeak(main, soft, fx) {
        var p = fx.p, amp = fx.amp || 1;
        var env = smooth(p / 0.14) * (1 - smooth((p - 0.66) / 0.31)) * amp;
        if (env < 0.01) return;
        var ctx = soft;
        // Every glow and streak fades smoothly to nothing (softSpot), so the
        // shapes melt into each other instead of showing their outlines
        // (the user saw the ellipses too cleanly, 2026-11-23).
        function blob(x, y, r, rgb, a) { softSpot(ctx, x, y, r, r, 0, rgb, 0.86 * a); }
        // Light pours in from the top-left and the bottom-right edges and
        // drifts slowly across. The middle of the far corners stays dark.
        blob(-260 + 980 * p, 110 + 90 * Math.sin(p * 2.6), 860, [255, 112, 40], 0.78 * env);
        blob(-120 + 520 * p, 520, 520, [255, 70, 50], 0.40 * env);
        blob(2160 - 760 * p, 990 - 60 * Math.sin(p * 2.1), 780, [255, 196, 88], 0.62 * env);
        blob(1260 + 240 * Math.sin(p * 1.7), -170, 600, [255, 70, 120], 0.36 * env);
        // A burnt-orange edge leak that breathes.
        var edgeA = 0.46 * env * (0.65 + 0.35 * Math.sin(p * 4.2));
        softSpot(ctx, -80, 330, 440, 660, 0, [255, 72, 40], edgeA);
        // Soft diagonal streaks sliding left to right at their own speeds.
        // Wide and overlapping, each fading out along its length and width.
        var streak = [[255, 170, 80], [255, 110, 60], [255, 226, 170], [255, 140, 90], [255, 200, 120],
            [255, 150, 70], [255, 214, 150]];
        for (var i = 0; i < streak.length; i++) {
            var w = 100 + 220 * ih(17, i, 1);
            var x = (-0.2 + 0.35 * ih(17, i, 2) + p * (0.35 + 0.45 * ih(17, i, 3))) * (W + 400);
            var len = 800 + 600 * ih(17, i, 7);
            var a = (0.22 + 0.24 * ih(17, i, 4)) * env;
            softSpot(ctx, x, 260 + 300 * ih(17, i, 8), w / 2, len / 2, -0.34 + 0.12 * (ih(17, i, 9) - 0.5), streak[i], a);
        }
        // Dust motes catching the light.
        for (var m = 0; m < 26; m++) {
            var mx = (ih(23, m, 1) * W + p * 160 * (0.5 + ih(23, m, 2))) % W;
            var my = ih(23, m, 3) * H - p * 60 * ih(23, m, 4);
            var mr = 4 + 8 * ih(23, m, 5);
            radial(ctx, mx, my, mr, [[0, 'rgba(255,236,200,' + (0.5 * env).toFixed(3) + ')'], [1, 'rgba(255,236,200,0)']]);
        }
        // A short, local flare that covers the swap.
        var wash = bell((p - 0.32) / 0.36);
        if (wash > 0.01) {
            blob(420 + 1100 * p, 380, 760, [255, 228, 196], 0.55 * wash * amp);
        }
        // A quick flash as the slides swap: up in a few frames, gone soon
        // after. It blooms from the flare, so the far corners stay dark.
        var fl = leakFlash(p) * amp;
        if (fl > 0.01) {
            var fxx = 420 + 1100 * p;
            blob(fxx, 430, 900, [255, 238, 214], 0.62 * fl);
            blob(fxx, 430, 340, [255, 252, 244], 0.9 * fl);
        }
        // Film grain in the light. Dark specks are punched out of the glow,
        // and fine bright specks go on the sharp canvas, kept to where the
        // glow is (the glow is their mask). Both change every video frame.
        var film = Math.floor(p * 24);
        ctx.save();
        ctx.globalCompositeOperation = 'destination-out';
        drawGrain(ctx, 0.3 * env, film + 31, 1, null, 'light');
        ctx.restore();
        if (main && main !== soft) {
            drawGrain(main, 0.75 * env, film, 1.25, null, 'light');
            main.save();
            main.setTransform(1, 0, 0, 1, 0, 0);
            main.globalCompositeOperation = 'destination-in';
            main.drawImage(soft.canvas, 0, 0, main.canvas.width, main.canvas.height);
            main.restore();
        }
    }
    function leakFlash(p) { return p < 0.45 ? smooth((p - 0.37) / 0.08) : 1 - smooth((p - 0.45) / 0.17); }

    function drawWarp(ctx, soft, fx) {
        var p = fx.p, amp = fx.amp || 1;
        var b = bell(p) * amp;
        if (b < 0.02) return;
        var cx = W / 2, cy = H / 2;
        // Centre bloom.
        radial(soft, cx, cy, 700, [[0, 'rgba(170,205,255,' + (0.22 * b).toFixed(3) + ')'], [1, 'rgba(170,205,255,0)']]);
        // Refraction rings rushing outward, split into colour fringes.
        for (var k = 0; k < 7; k++) {
            var r = (p * 1.75 - k * 0.13) * 1400;
            if (r < 20 || r > 2300) continue;
            var a = b * 0.55 * (1 - r / 2300);
            var fringe = [[255, 90, 90, -6], [255, 255, 255, 0], [80, 200, 255, 6]];
            var wave = function (c2, off) {
                c2.beginPath();
                for (var j = 0; j <= 120; j++) {
                    var t = j / 120;
                    var rr = r * (1 + 0.09 * (vnoiseP(29 + k * 7, t * 9 + p * 2.5, 9) - 0.5) * 2) + off;
                    var x = cx + Math.cos(t * TAU) * rr, y = cy + Math.sin(t * TAU) * rr * 0.6;
                    if (j) c2.lineTo(x, y); else c2.moveTo(x, y);
                }
            };
            wave(soft, 0);
            soft.lineWidth = 34;
            soft.strokeStyle = 'rgba(90,200,255,' + (a * 0.14).toFixed(3) + ')';
            soft.stroke();
            for (var f = 0; f < 3; f++) {
                wave(ctx, fringe[f][3]);
                ctx.lineWidth = 1.5 + 4 * (1 - r / 2300);
                ctx.strokeStyle = 'rgba(' + fringe[f][0] + ',' + fringe[f][1] + ',' + fringe[f][2] + ',' + (a * (f === 1 ? 0.8 : 1)).toFixed(3) + ')';
                ctx.stroke();
            }
        }
        // Radial zoom streaks.
        ctx.lineCap = 'round';
        for (var i = 0; i < 170; i++) {
            var ang = ih(29, i, 1) * TAU;
            var r0 = 90 + ih(29, i, 2) * 760 + p * 900;
            var len = (40 + 280 * ih(29, i, 3)) * b;
            var al = 0.38 * b * ih(29, i, 4);
            var pick = ih(29, i, 5);
            ctx.strokeStyle = pick < 0.6 ? 'rgba(235,242,255,' + al.toFixed(3) + ')'
                : pick < 0.85 ? 'rgba(90,220,255,' + al.toFixed(3) + ')' : 'rgba(245,184,61,' + al.toFixed(3) + ')';
            ctx.lineWidth = 1 + 2 * ih(29, i, 6);
            ctx.beginPath();
            ctx.moveTo(cx + Math.cos(ang) * r0, cy + Math.sin(ang) * r0 * 0.62);
            ctx.lineTo(cx + Math.cos(ang) * (r0 + len), cy + Math.sin(ang) * (r0 + len) * 0.62);
            ctx.stroke();
        }
    }

    function drawStrobe(ctx, soft, fx, g) {
        // Steady light: the strength only eases in and out (no per-frame random
        // jumps or whole-frame flashes; the user found those flickery, 2026-11-23).
        var p = fx.p, amp = fx.amp || 1, sn = g.sn, x = g.x;
        var env = smooth(p / 0.12) * (1 - smooth((p - 0.82) / 0.16));
        var I = env * amp;
        if (env < 0.01) return;
        // Exposure flash on the slides around the bar.
        var main = ctx;
        ctx = soft;
        var ex = ctx.createLinearGradient(x - 520, 0, x + 360, 0);
        ex.addColorStop(0, 'rgba(255,248,235,0)');
        ex.addColorStop(0.5, 'rgba(255,248,235,' + (0.20 * I).toFixed(3) + ')');
        ex.addColorStop(0.59, 'rgba(255,248,235,' + (0.34 * I).toFixed(3) + ')');
        ex.addColorStop(0.7, 'rgba(255,248,235,' + (0.14 * I).toFixed(3) + ')');
        ex.addColorStop(1, 'rgba(255,248,235,0)');
        ctx.fillStyle = ex;
        ctx.fillRect(x - 520, 0, 880, H);
        // Bloom halo.
        ctx.save();
        ctx.translate(x, H / 2);
        ctx.scale(0.55, 1.25);
        var halo = ctx.createRadialGradient(0, 0, 0, 0, 0, 560);
        halo.addColorStop(0, 'rgba(160,220,255,' + (0.34 * I).toFixed(3) + ')');
        halo.addColorStop(1, 'rgba(160,220,255,0)');
        ctx.fillStyle = halo;
        ctx.fillRect(-560, -560, 1120, 1120);
        ctx.restore();
        // Coloured glow, then the white-hot core.
        var gl = ctx.createLinearGradient(x - 170, 0, x + 170, 0);
        gl.addColorStop(0, 'rgba(76,141,255,0)');
        gl.addColorStop(0.36, 'rgba(90,200,255,' + (0.55 * I).toFixed(3) + ')');
        gl.addColorStop(0.5, 'rgba(230,248,255,' + (0.85 * I).toFixed(3) + ')');
        gl.addColorStop(0.64, 'rgba(245,184,61,' + (0.45 * I).toFixed(3) + ')');
        gl.addColorStop(1, 'rgba(245,184,61,0)');
        ctx.fillStyle = gl;
        ctx.fillRect(x - 170, 0, 340, H);
        ctx = main;
        var cw = 16;
        ctx.fillStyle = 'rgba(255,255,255,' + Math.min(1, 0.6 + 0.4 * I).toFixed(3) + ')';
        ctx.fillRect(x - cw / 2, 0, cw, H);
        // Slivers running ahead and trailing behind the bar, at a steady strength.
        var sl = [[-46, 5, 0.65], [-108, 3, 0.48], [-186, 7, 0.32], [-300, 2, 0.26], [-430, 4, 0.16], [38, 3, 0.45], [86, 2, 0.24]];
        for (var i = 0; i < sl.length; i++) {
            ctx.fillStyle = (i % 3 === 1 ? 'rgba(120,215,255,' : i % 3 === 2 ? 'rgba(255,214,140,' : 'rgba(255,255,255,')
                + (sl[i][2] * 0.8 * I).toFixed(3) + ')';
            ctx.fillRect(x + sl[i][0] - sl[i][1] / 2, 0, sl[i][1], H);
        }
        // Faint vertical streaks that travel with the bar.
        for (var s = 0; s < 34; s++) {
            var dx = (ih(sn, s, 10) - 0.5) * 900;
            var a = 0.18 * I * (1 - Math.abs(dx) / 450) * ih(sn, s, 11);
            if (a < 0.01) continue;
            var y0 = ih(sn, s, 12) * H * 0.7, y1 = y0 + (0.2 + 0.6 * ih(sn, s, 13)) * H;
            ctx.fillStyle = 'rgba(220,240,255,' + a.toFixed(3) + ')';
            ctx.fillRect(x + dx, y0, 1 + ih(sn, s, 14) * 1.5, y1 - y0);
        }
        // Anamorphic flare across the frame, and lens ghosts.
        var fy = H * (0.38 + 0.24 * ih(sn, 1, 15));
        var an = ctx.createLinearGradient(x - 1100, 0, x + 1100, 0);
        an.addColorStop(0, 'rgba(100,180,255,0)');
        an.addColorStop(0.5, 'rgba(160,215,255,' + (0.6 * I).toFixed(3) + ')');
        an.addColorStop(1, 'rgba(100,180,255,0)');
        ctx.fillStyle = an;
        ctx.fillRect(x - 1100, fy - 2, 2200, 4);
        ctx.fillRect(x - 1100, fy + 26, 2200, 1.5);
        for (var gi = 0; gi < 4; gi++) {
            var gx = W / 2 + (W / 2 - x) * (0.35 + 0.4 * gi), gy = H / 2 + (H / 2 - fy) * (0.3 + 0.35 * gi);
            var gr = 26 + 70 * ih(sn, gi, 16);
            var gg = ctx.createRadialGradient(gx, gy, gr * 0.3, gx, gy, gr);
            gg.addColorStop(0, rgba(gi % 2 ? GOLD : CYAN, 0));
            gg.addColorStop(0.8, rgba(gi % 2 ? GOLD : CYAN, 0.14 * I));
            gg.addColorStop(1, rgba(gi % 2 ? GOLD : CYAN, 0));
            ctx.fillStyle = gg;
            ctx.fillRect(gx - gr, gy - gr, gr * 2, gr * 2);
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

    var BLEND = { lightleak: 'screen', shatter: 'screen', warp: 'screen' };
    var SOFT = { lightleak: 1, shatter: 1, warp: 1, burn: 1 };
    // Overlay resolution. Ink, burn and glitch marks are organic or noisy, so
    // half resolution looks the same at a quarter of the drawing cost.
    var RES = { paint: 0.5, burn: 0.5, glitch: 0.5 };

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
                    return { inn: s, out: slides[i - 1], p: (t - s.t0) / s.fxDur, style: s.fx, amp: s.fxAmp || 1,
                        dur: s.fxDur, seed: s.el.id || ('fx' + i) };
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
            var live = !!fx && fx.p <= 0.985;
            var ctx = overlayCtx(live ? BLEND[fx.style] : '', live, live ? RES[fx.style] || 1 : 1);
            var soft = softCtx(live ? BLEND[fx.style] : '', live && !!SOFT[fx.style]);
            if (!ctx || !live) return;
            if (!fx.seed) fx.seed = (fx.inn && fx.inn.el && fx.inn.el.id) || 'fx';
            var g = geometry(fx);
            if (SOFT[fx.style] && !soft) soft = ctx;     // no stage yet: draw it all on one canvas
            ctx.save();
            if (soft && soft !== ctx) soft.save();
            if (fx.style === 'glitch') drawGlitch(ctx, fx, g);
            else if (fx.style === 'paint') drawInk(ctx, fx, g);
            else if (fx.style === 'burn') drawBurn(ctx, soft, fx, g);
            else if (fx.style === 'pixel') drawPixel(ctx, fx, g);
            else if (fx.style === 'lightleak') drawLeak(ctx, soft, fx);
            else if (fx.style === 'shatter') drawStrobe(ctx, soft, fx, g);
            else if (fx.style === 'warp') drawWarp(ctx, soft, fx);
            if (soft && soft !== ctx) soft.restore();
            ctx.restore();
        }
    };
})();
