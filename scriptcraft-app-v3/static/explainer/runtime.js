/* Explainer video runtime. Every frame is a pure function of time t, so the
   live preview (driven by the dialog's audio over postMessage) and the
   renderer (headless Chrome calling __seek(t) per frame) show the same thing.
   Slides, cues and camera keys carry times the server resolved from the
   narration (data-t0/t1, data-t, data-tout, data-camt). Slides with
   data-host leave the presenter's area see-through: the renderer puts the
   footage under the frame, the preview plays a small copy of it there. */
(function () {
    'use strict';
    var CFG = window.__EXPLAINER || {};
    var MODE = CFG.mode || 'preview';
    var DUR = +CFG.duration || 1;
    var SECTIONS = CFG.sections || [];
    var HOST = CFG.host || { on: false };
    var LAYOUTS = HOST.layouts || {};
    var SECS = HOST.sections || [];      // presenter sections the user placed: {t0, t1, layout}
    var SFADE = +HOST.fade || 0.3;
    var TR = 0.4;          // slide transition
    var CAM = 1.6;         // camera move
    var DEF = { rise: 0.6, words: 0.5, left: 0.6, right: 0.6, up: 0.6, down: 0.6, pop: 0.55, stamp: 0.35,
                fade: 0.5, wipe: 0.8, 'wipe-up': 0.8, draw: 1.2, count: 1.2, zoom: 0, ring: 0.9 };
    var SHAPES = 'path,line,polyline,polygon,rect,circle,ellipse';

    var stage = document.getElementById('stage');
    var canvas = document.getElementById('bg');
    var ctx = canvas.getContext('2d');
    var hudL = document.getElementById('hud-left');
    var hudR = document.getElementById('hud-right');
    var hud = document.getElementById('hud');
    var bar = document.getElementById('progress');

    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    var E = {
        out: function (p) { return 1 - Math.pow(1 - p, 3); },
        inout: function (p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; },
        back: function (p) { var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); }
    };
    function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 1000) / 1000; }

    // ---- particle background: ~20 rows riding slow waves, packed toward the
    // bottom and fading out by mid-screen. Flat colors, no gradients.
    var ROWS = [];
    (function () {
        for (var r = 0; r < 20; r++) {
            var f = r / 19;
            ROWS.push({
                y: 1068 - Math.pow(f, 1.55) * 500,
                amp: 6 + 10 * f, len: 220 + 160 * hash('l' + r), spd: 0.25 + 0.35 * hash('s' + r),
                drift: (hash('d' + r) - 0.5) * 14, gap: 15 + Math.round(f * 9), rad: 1.9 - 0.7 * f,
                alpha: 0.55 * Math.pow(1 - f, 1.35) + 0.04, phase: hash('p' + r) * 6.283,
                color: r % 5 === 2 ? '245,184,61' : '118,138,186'
            });
        }
    })();
    function roundRect(x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }
    var dpr = 0;
    function drawBg(t, holes) {
        var k = window.devicePixelRatio || 1;
        if (k !== dpr) { dpr = k; canvas.width = 1920 * k; canvas.height = 1080 * k; canvas.style.width = '1920px'; canvas.style.height = '1080px'; }
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.fillStyle = '#090c12';
        ctx.fillRect(0, 0, 1920, 1080);
        for (var r = 0; r < ROWS.length; r++) {
            var row = ROWS[r];
            ctx.fillStyle = 'rgba(' + row.color + ',' + row.alpha.toFixed(3) + ')';
            var off = ((t * row.drift) % row.gap + row.gap) % row.gap;
            ctx.beginPath();
            for (var x = -row.gap + off; x < 1920 + row.gap; x += row.gap) {
                var y = row.y + Math.sin(x / row.len * 6.283 + t * row.spd + row.phase) * row.amp;
                ctx.moveTo(x + row.rad, y);
                ctx.arc(x, y, row.rad, 0, 6.283);
            }
            ctx.fill();
        }
        // Presenter areas: cut out, as far as the slide showing them is faded in.
        for (var name in holes || {}) {
            var L = LAYOUTS[name], o = holes[name];
            if (!L || !(o > 0)) continue;
            ctx.save();
            ctx.globalCompositeOperation = 'destination-out';
            ctx.globalAlpha = Math.min(1, o);
            ctx.fillStyle = '#000';      // opaque: the cut-out uses the fill's alpha too
            roundRect(L.x, L.y, L.w, L.h, L.r || 0);
            ctx.fill();
            ctx.restore();
        }
    }

    // ---- presenter video in the preview (the renderer composites the real footage)
    var hostVid = null;
    if (HOST.on && HOST.video && MODE === 'preview') {
        hostVid = document.createElement('video');
        hostVid.muted = true; hostVid.playsInline = true; hostVid.preload = 'auto';
        hostVid.src = HOST.video;
        hostVid.style.cssText = 'position:absolute; left:0; top:0; width:1920px; height:1080px; object-fit:cover; visibility:hidden;';
        stage.insertBefore(hostVid, canvas);
    }
    function placeHost(holes) {
        if (!hostVid) return;
        var best = null, bo = 0;
        for (var n in holes) if (holes[n] > bo) { bo = holes[n]; best = n; }
        var L = best && LAYOUTS[best];
        if (!L) { hostVid.style.visibility = 'hidden'; return; }
        var asp = hostVid.videoWidth && hostVid.videoHeight ? hostVid.videoWidth / hostVid.videoHeight : 16 / 9;
        var sw = Math.max(L.w, L.h * asp), over = sw - L.w;
        var focus = (best === 'left' || best === 'right') ? (+HOST.focus || 0.5) : 0.5;
        var pct = over > 0.5 ? clamp((focus * sw - L.w / 2) / over, 0, 1) * 100 : 50;
        var st = hostVid.style;
        st.visibility = ''; st.left = L.x + 'px'; st.top = L.y + 'px'; st.width = L.w + 'px'; st.height = L.h + 'px';
        st.objectPosition = pct.toFixed(2) + '% 50%';
        st.borderRadius = (L.r || 0) + 'px';
    }
    function syncHost(t, playing) {
        if (!hostVid || hostVid.readyState < 1) return;
        var want = clamp(t, 0, hostVid.duration || t);
        if (playing) {
            if (hostVid.paused) {
                hostVid.currentTime = want;
                var pr = hostVid.play();
                if (pr && pr.catch) pr.catch(function () {});
            } else if (Math.abs(hostVid.currentTime - want) > 0.3) hostVid.currentTime = want;
        } else {
            if (!hostVid.paused) hostVid.pause();
            if (Math.abs(hostVid.currentTime - want) > 0.04) hostVid.currentTime = want;
        }
    }

    // ---- slides
    var slides = Array.prototype.map.call(document.querySelectorAll('#slides > section.slide'), function (el, i) {
        return { el: el, i: i, t0: +el.dataset.t0, t1: +el.dataset.t1, kind: el.dataset.kind || 'slide',
                 hud: el.dataset.hud !== 'off', sidx: +el.dataset.sidx, label: el.dataset.slabel || '',
                 tracker: el.dataset.tracker || '', trans: el.dataset.transition || 'push',
                 host: HOST.on && LAYOUTS[el.dataset.host] ? el.dataset.host : '',
                 items: [], cams: [], prepped: false };
    });

    function baseTransform(e) {
        var b = e.style.transform || '';
        e.__base = b && b !== 'none' ? b + ' ' : '';
    }

    // An SVG element with its own transform attribute moves inside a new <g>,
    // so animating the CSS transform does not wipe out its placement.
    function wrapSvg(e) {
        if (!(e instanceof SVGElement) || e.tagName.toLowerCase() === 'svg' || !e.hasAttribute('transform')) return e;
        var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        e.parentNode.insertBefore(g, e);
        g.appendChild(e);
        ['data-anim', 'data-t', 'data-delay', 'data-dur', 'data-loop', 'data-speed', 'data-tout', 'data-out'].forEach(function (a) {
            if (e.hasAttribute(a)) { g.setAttribute(a, e.getAttribute(a)); e.removeAttribute(a); }
        });
        return g;
    }

    function splitWords(e) {
        var walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT, null);
        var nodes = [], n;
        while ((n = walker.nextNode())) nodes.push(n);
        var spans = [];
        nodes.forEach(function (node) {
            var parts = node.nodeValue.split(/(\s+)/);
            var frag = document.createDocumentFragment();
            parts.forEach(function (p) {
                if (!p) return;
                if (/^\s+$/.test(p)) { frag.appendChild(document.createTextNode(p)); return; }
                var s = document.createElement('span');
                s.className = 'w';
                s.textContent = p;
                frag.appendChild(s);
                spans.push(s);
            });
            node.parentNode.replaceChild(frag, node);
        });
        return spans;
    }

    function fmtNum(v, it) {
        var s = v.toFixed(it.decimals);
        if (it.comma) { var p = s.split('.'); p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ','); s = p.join('.'); }
        return it.prefix + s + it.suffix;
    }

    function prep(s) {
        if (s.prepped) return;
        s.prepped = true;
        var el = s.el;
        // Staggered containers hand their animation to their children.
        el.querySelectorAll('[data-stagger]').forEach(function (c) {
            var gap = +c.dataset.stagger || 0.12;
            var anim = c.dataset.anim || 'rise';
            var t = c.dataset.t !== undefined ? +c.dataset.t : s.t0 + 0.15;
            var delay = +c.dataset.delay || 0;
            Array.prototype.forEach.call(c.children, function (k, j) {
                if (k.tagName === 'STYLE') return;
                if (!k.dataset.anim) k.dataset.anim = anim.replace(/\bring\b/, '').trim() || 'rise';
                if (k.dataset.t === undefined) k.dataset.t = (t + delay + j * gap).toFixed(3);
            });
            c.removeAttribute('data-anim');
        });
        var seen = new Set();
        el.querySelectorAll('[data-anim],[data-loop],[data-tout]').forEach(function (e0) {
            var e = wrapSvg(e0);
            if (seen.has(e)) return;
            seen.add(e);
            baseTransform(e);
            var kinds = (e.dataset.anim || '').split(/\s+/).filter(Boolean);
            var main = kinds.filter(function (k) { return k !== 'ring'; })[0] || '';
            var t = e.dataset.t !== undefined ? +e.dataset.t : s.t0 + 0.15;
            t += +e.dataset.delay || 0;
            var it = { e: e, main: main, t: t, dur: e.dataset.dur ? +e.dataset.dur : (main === 'zoom' ? Math.max(1, s.t1 - t) : (DEF[main] || 0.6)),
                       ring: kinds.indexOf('ring') >= 0, loop: e.dataset.loop || '', speed: +e.dataset.speed || 1,
                       ph: hash(e.textContent.slice(0, 20) + (e.getAttribute('class') || '') + s.i + seen.size),
                       tout: e.dataset.tout !== undefined ? +e.dataset.tout : null, out: e.dataset.out || 'fade' };
            if (main === 'words') it.words = splitWords(e);
            if (main === 'draw') {
                var shapes = e.matches(SHAPES) ? [e] : Array.prototype.slice.call(e.querySelectorAll(SHAPES));
                it.shapes = shapes.map(function (sh) {
                    sh.setAttribute('pathLength', '1');
                    sh.style.strokeDasharray = '1 1';
                    var fill = sh.getAttribute('fill') || getComputedStyle(sh).fill;
                    return { sh: sh, fill: fill && fill !== 'none' };
                });
            }
            if (main === 'count') {
                var txt = e.textContent.trim();
                var m = txt.match(/-?\d[\d,]*(?:\.\d+)?/);
                var to = e.dataset.to !== undefined ? +e.dataset.to : (m ? +m[0].replace(/,/g, '') : 0);
                var dec = e.dataset.decimals !== undefined ? +e.dataset.decimals : (m && m[0].indexOf('.') >= 0 ? m[0].split('.')[1].length : 0);
                it.count = { from: +(e.dataset.from || 0), to: to, decimals: dec,
                             prefix: e.dataset.prefix !== undefined ? e.dataset.prefix : (m ? txt.slice(0, m.index) : ''),
                             suffix: e.dataset.suffix !== undefined ? e.dataset.suffix : (m ? txt.slice(m.index + m[0].length) : ''),
                             comma: e.dataset.comma === '1' || (m && m[0].indexOf(',') >= 0) };
            }
            s.items.push(it);
        });
        el.querySelectorAll('[data-camt]').forEach(function (c) {
            var keys = c.dataset.camt.split(';').map(function (k) { var v = k.split(',').map(Number); return { t: v[0], x: v[1], y: v[2], z: v[3] || 1 }; })
                .filter(function (k) { return !isNaN(k.t); }).sort(function (a, b) { return a.t - b.t; });
            if (keys.length) s.cams.push({ e: c, keys: keys });
        });
    }

    function ringFor(s, it) {
        if (it.ringEl) return it.ringEl;
        var r = document.createElement('div');
        r.className = 'ring-fx';
        s.el.appendChild(r);
        it.ringEl = r;
        return r;
    }

    function placeRing(s, it) {
        var r = ringFor(s, it);
        var k = stageScale();
        var sr = s.el.getBoundingClientRect(), er = it.e.getBoundingClientRect();
        var cx = (er.left + er.width / 2 - sr.left) / k, cy = (er.top + er.height / 2 - sr.top) / k;
        var d = Math.max(140, Math.max(er.width, er.height) / k * 0.9);
        r.style.left = (cx - d / 2) + 'px'; r.style.top = (cy - d / 2) + 'px';
        r.style.width = d + 'px'; r.style.height = d + 'px';
        it.ringPlaced = true;
    }

    function apply(s, it, t) {
        var e = it.e, o = 1, tf = '', clip = '';
        var r = clamp((t - it.t) / (it.dur || 0.001), 0, 1), p = E.out(r);
        switch (it.main) {
            case 'rise': o = p; tf = 'translateY(' + ((1 - p) * 40).toFixed(2) + 'px)'; break;
            case 'fade': o = p; break;
            case 'left': o = p; tf = 'translateX(' + (-(1 - p) * 120).toFixed(2) + 'px)'; break;
            case 'right': o = p; tf = 'translateX(' + ((1 - p) * 120).toFixed(2) + 'px)'; break;
            case 'up': o = p; tf = 'translateY(' + ((1 - p) * 120).toFixed(2) + 'px)'; break;
            case 'down': o = p; tf = 'translateY(' + (-(1 - p) * 120).toFixed(2) + 'px)'; break;
            case 'pop': o = clamp(r * 3, 0, 1); tf = 'scale(' + (0.5 + 0.5 * E.back(r)).toFixed(4) + ')'; break;
            case 'stamp': o = clamp(r * 4, 0, 1); tf = 'scale(' + (1.7 - 0.7 * p).toFixed(4) + ')'; break;
            case 'zoom': o = clamp((t - it.t) / 0.3 + 1, 0, 1); tf = 'scale(' + (1 + 0.07 * E.inout(r)).toFixed(4) + ')'; break;
            case 'wipe': clip = r >= 1 ? 'none' : 'inset(-2% ' + ((1 - p) * 102).toFixed(2) + '% -2% -2%)'; break;
            case 'wipe-up': clip = r >= 1 ? 'none' : 'inset(' + ((1 - p) * 102).toFixed(2) + '% -2% -2% -2%)'; break;
            case 'draw':
                it.shapes.forEach(function (x) {
                    x.sh.style.strokeDashoffset = (1 - E.inout(r)).toFixed(4);
                    if (x.fill) x.sh.style.fillOpacity = clamp((r - 0.6) / 0.4, 0, 1).toFixed(3);
                });
                o = t >= it.t ? 1 : 0;
                break;
            case 'count':
                o = clamp(r * 5, 0, 1);
                e.textContent = fmtNum(it.count.from + (it.count.to - it.count.from) * E.inout(r), it.count);
                break;
            case 'words':
                it.words.forEach(function (w, j) {
                    var q = E.out(clamp((t - it.t - j * 0.07) / it.dur, 0, 1));
                    w.style.opacity = q.toFixed(3);
                    w.style.transform = 'translateY(' + ((1 - q) * 0.42).toFixed(3) + 'em)';
                });
                break;
        }
        if (it.loop) {
            var w = it.speed, ph = it.ph * 6.283;
            switch (it.loop) {
                case 'float': tf += ' translateY(' + (Math.sin(t * 1.57 * w + ph) * 8).toFixed(2) + 'px)'; break;
                case 'drift': tf += ' translateX(' + (Math.sin(t * 0.45 * w + ph) * 24).toFixed(2) + 'px)'; break;
                case 'spin': tf += ' rotate(' + ((t * 24 * w + ph * 57) % 360).toFixed(2) + 'deg)'; break;
                case 'pulse': tf += ' scale(' + (1 + 0.045 * Math.sin(t * 3.9 * w + ph)).toFixed(4) + ')'; break;
                case 'blink': o *= Math.sin(t * 5.2 * w + ph) > -0.2 ? 1 : 0.25; break;
                case 'twinkle': o *= 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * (1.4 + it.ph) * w + ph * 3)); break;
            }
        }
        if (it.tout !== null && t >= it.tout) {
            var q = E.out(clamp((t - it.tout) / 0.35, 0, 1));
            o *= 1 - q;
            if (it.out === 'down') tf += ' translateY(' + (q * 60).toFixed(2) + 'px)';
            else if (it.out === 'shrink') tf += ' scale(' + (1 - 0.4 * q).toFixed(4) + ')';
        }
        e.style.opacity = o >= 1 ? '' : o.toFixed(3);
        var full = (e.__base + tf).trim();
        e.style.transform = full;
        if (clip) e.style.clipPath = clip === 'none' ? '' : clip;
        if (it.ring) {
            var rr = (t - it.t) / 0.9;
            var ring = ringFor(s, it);
            if (rr >= 0 && rr <= 1) {
                if (!it.ringPlaced) placeRing(s, it);
                var q2 = E.out(rr);
                ring.style.opacity = ((1 - q2) * 0.9).toFixed(3);
                ring.style.transform = 'scale(' + (0.35 + 1.25 * q2).toFixed(4) + ')';
            } else ring.style.opacity = '0';
        }
    }

    function camera(c, t) {
        var k = c.keys, x = k[0].x, y = k[0].y, z = k[0].z;
        for (var i = 1; i < k.length; i++) {
            if (t <= k[i].t) break;
            var q = E.inout(clamp((t - k[i].t) / CAM, 0, 1));
            x += (k[i].x - x) * q; y += (k[i].y - y) * q; z += (k[i].z - z) * q;
        }
        c.e.style.transform = 'translate(' + (960 - x * z).toFixed(2) + 'px,' + (540 - y * z).toFixed(2) + 'px) scale(' + z.toFixed(4) + ')';
    }

    function transitionOf(s) { var n = slides[s.i + 1]; return n ? n.trans : 'cut'; }

    var active = [];
    function seek(t) {
        t = clamp(+t || 0, 0, DUR);
        var vis = [], holes = {};
        for (var i = 0; i < slides.length; i++) {
            var s = slides[i];
            var tail = transitionOf(s) === 'cut' ? 0 : TR;
            if (t >= s.t0 && t < s.t1 + tail) vis.push(s);
            else if (s.t0 > t + 1) break;
        }
        active.forEach(function (s) { if (vis.indexOf(s) < 0) s.el.classList.remove('on'); });
        var hudW = 0, labelS = null, labelW = -1;
        vis.forEach(function (s) {
            prep(s);
            s.el.classList.add('on');
            var o = 1, ty = 0;
            if (t < s.t0 + TR && s.i > 0 && s.trans !== 'cut') {
                var q = E.out(clamp((t - s.t0) / TR, 0, 1));
                o = q; ty = s.trans === 'push' ? (1 - q) * 70 : 0;
            }
            if (t >= s.t1) {
                var q2 = E.inout(clamp((t - s.t1) / TR, 0, 1));
                o *= 1 - q2; ty -= transitionOf(s) === 'push' ? q2 * 90 : 0;
            }
            s.el.style.opacity = o >= 1 ? '' : o.toFixed(3);
            s.el.style.transform = ty ? 'translateY(' + ty.toFixed(2) + 'px)' : '';
            if (s.host) holes[s.host] = Math.max(holes[s.host] || 0, o);
            s.el.style.zIndex = String(s.i + 1);
            for (var j = 0; j < s.items.length; j++) apply(s, s.items[j], t);
            for (var c = 0; c < s.cams.length; c++) camera(s.cams[c], t);
            if (s.hud) hudW = Math.max(hudW, o);
            if (o > labelW) { labelW = o; labelS = s; }
        });
        active = vis;
        // Sections the user placed win over a slide's own presenter layout
        // (the two cross-fade at the section's edges).
        var sh = {}, smax = 0;
        for (var q = 0; q < SECS.length; q++) {
            var x = SECS[q];
            if (t <= x.t0 || t >= x.t1) continue;
            var oq = clamp(Math.min((t - x.t0) / SFADE, (x.t1 - t) / SFADE), 0, 1);
            sh[x.layout] = Math.max(sh[x.layout] || 0, oq);
            smax = Math.max(smax, oq);
        }
        if (smax > 0) {
            for (var hn in holes) holes[hn] *= 1 - smax;
            for (var sn in sh) holes[sn] = Math.max(holes[sn] || 0, sh[sn]);
        }
        drawBg(t, holes);
        placeHost(holes);
        // The HUD gets a dark backing where it sits over the presenter.
        hud.classList.toggle('over-left', (holes.full || holes.left || 0) > 0.5);
        hud.classList.toggle('over-right', (holes.full || holes.right || 0) > 0.5);
        hud.style.opacity = hudW.toFixed(3);
        if (labelS) {
            if (hudL.textContent !== labelS.label) hudL.textContent = labelS.label;
            var key = labelS.tracker ? 't:' + labelS.tracker : 'd:' + labelS.sidx;
            if (hudR.__key !== key) {
                hudR.__key = key;
                if (labelS.tracker) hudR.textContent = labelS.tracker;
                else {
                    hudR.innerHTML = '';
                    if (SECTIONS.length > 1) SECTIONS.forEach(function (_n, k) {
                        var d = document.createElement('span');
                        d.className = 'dot' + (k < labelS.sidx ? ' done' : k === labelS.sidx ? ' cur' : '');
                        hudR.appendChild(d);
                    });
                }
            }
        }
        bar.style.width = (t / DUR * 1920).toFixed(2) + 'px';
        return t;
    }

    function stageScale() { return MODE === 'preview' ? (stage.__k || 1) : 1; }

    // ---- layout checks: run on each slide fully built (just before it ends).
    function rectOf(e, k, sr) {
        var r = e.getBoundingClientRect();
        return { x: (r.left - sr.left) / k, y: (r.top - sr.top) / k, w: r.width / k, h: r.height / k };
    }
    // The element's own text, line by line, trimmed to the middle of each line
    // (roughly the glyphs), so padding and loose line boxes don't count as overlaps.
    function textRect(e, k, sr) {
        var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        Array.prototype.forEach.call(e.childNodes, function (n) {
            if (n.nodeType !== 3 || !n.nodeValue.trim()) return;
            var range = document.createRange();
            range.selectNodeContents(n);
            Array.prototype.forEach.call(range.getClientRects(), function (q) {
                if (q.width < 1 || q.height < 1) return;
                x0 = Math.min(x0, q.left); x1 = Math.max(x1, q.right);
                y0 = Math.min(y0, q.top + q.height * 0.2); y1 = Math.max(y1, q.bottom - q.height * 0.2);
            });
        });
        if (x0 === Infinity) return rectOf(e, k, sr);
        return { x: (x0 - sr.left) / k, y: (y0 - sr.top) / k, w: (x1 - x0) / k, h: (y1 - y0) / k };
    }
    function inter(a, b) {
        var w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        return w > 0 && h > 0 ? w * h : 0;
    }
    function label(e) { return (e.textContent || e.getAttribute('alt') || e.tagName).trim().replace(/\s+/g, ' ').slice(0, 40); }
    function visible(e) {
        for (var x = e; x && x.tagName !== 'SECTION'; x = x.parentElement) {
            var cs = getComputedStyle(x);
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity < 0.05) return false;
        }
        return true;
    }
    // Text, images and illustrations of slide s as they are on screen now.
    function boxesOf(s, k, sr) {
        var texts = [], imgs = [];
        s.el.querySelectorAll('*').forEach(function (e) {
            if (e.closest('.camera')) return;
            var tag = e.tagName.toLowerCase();
            if (tag === 'img' || tag === 'image') { if (visible(e)) imgs.push(e); return; }
            if (tag === 'style' || e.classList.contains('ring-fx')) return;
            var own = Array.prototype.some.call(e.childNodes, function (n) { return n.nodeType === 3 && n.nodeValue.trim(); });
            if (own && visible(e)) texts.push(e);
        });
        return texts.map(function (e) { return { e: e, r: textRect(e, k, sr), text: true }; })
            .concat(imgs.map(function (e) { return { e: e, r: rectOf(e, k, sr), text: false }; }));
    }
    // Nothing may cover the presenter: text, logos or illustrations in its
    // area (for full frame, around the face), or an opaque block over it.
    function presenterIssues(s, layout, boxes, k, sr, issues) {
        var L = LAYOUTS[layout];
        if (!L) return;
        var zone = layout === 'full' ? { x: (+HOST.focus || 0.5) * 1920 - 330, y: 40, w: 660, h: 760 } : L;
        boxes.forEach(function (b) {
            var r = b.r;
            if (r.w >= 2 && r.h >= 2 && inter(r, zone) > 0.2 * Math.min(r.w * r.h, zone.w * zone.h))
                issues.push('“' + label(b.e) + '” covers the presenter');
        });
        s.el.querySelectorAll('svg').forEach(function (e) {
            if (e.parentElement.closest('svg') || e.classList.contains('fill') || !visible(e)) return;
            var r = rectOf(e, k, sr);
            if (r.w >= 8 && r.h >= 8 && inter(r, zone) > 0.2 * Math.min(r.w * r.h, zone.w * zone.h))
                issues.push('an illustration covers the presenter');
        });
        s.el.querySelectorAll('div, svg, img, section > *').forEach(function (e) {
            if (!visible(e)) return;
            var cs = getComputedStyle(e), bg = cs.backgroundColor || '';
            var m = bg.match(/rgba?\(([^)]+)\)/), alpha = m ? (m[1].split(',')[3] === undefined ? 1 : +m[1].split(',')[3]) : 0;
            var solid = alpha > 0.5 || e.classList.contains('scene') || (e.tagName.toLowerCase() === 'svg' && e.classList.contains('fill'));
            if (!solid) return;
            var r = rectOf(e, k, sr);
            if (inter(r, L) > 0.3 * L.w * L.h) issues.push('a ' + (e.classList.contains('scene') ? 'scene' : 'background') + ' covers the presenter');
        });
    }
    function check() {
        var out = [];
        var k = stageScale();
        slides.forEach(function (s) {
            var tt = Math.max(s.t0 + 0.45, s.t1 - 0.05);
            seek(tt);
            var sr = stage.getBoundingClientRect();
            var issues = [];
            var boxes = boxesOf(s, k, sr);
            boxes.forEach(function (b) {
                var r = b.r;
                if (r.w < 2 || r.h < 2) return;
                if (r.x < -2 || r.y < -2 || r.x + r.w > 1922 || r.y + r.h > 1082)
                    issues.push('“' + label(b.e) + '” runs off the frame');
                else if (s.hud && b.text && ((r.y < 96 && (r.x < 720 || r.x + r.w > 1300)) || r.y + r.h > 1066))
                    issues.push('“' + label(b.e) + '” sits under the HUD');
            });
            if (s.host) presenterIssues(s, s.host, boxes, k, sr, issues);
            for (var a = 0; a < boxes.length; a++) for (var b = a + 1; b < boxes.length; b++) {
                var A = boxes[a], B = boxes[b];
                if (!A.text && !B.text) continue;
                if (A.e.contains(B.e) || B.e.contains(A.e)) continue;
                var area = inter(A.r, B.r), small = Math.min(A.r.w * A.r.h, B.r.w * B.r.h);
                if (small > 40 && area > 0.15 * small)
                    issues.push('“' + label(A.e) + '” overlaps “' + label(B.e) + '”');
            }
            // The user's presenter sections on this slide, checked halfway through each overlap.
            SECS.forEach(function (x) {
                var a0 = Math.max(s.t0 + 0.45, x.t0), a1 = Math.min(s.t1, x.t1);
                if (a1 - a0 < 0.2) return;
                seek((a0 + a1) / 2);
                presenterIssues(s, x.layout, boxesOf(s, k, sr), k, sr, issues);
            });
            if (issues.length) out.push({ id: s.el.id, issues: issues.filter(function (v, i, arr) { return arr.indexOf(v) === i; }).slice(0, 8) });
        });
        return out;
    }

    // ---- fit the stage to the window in preview mode
    function fit() {
        if (MODE !== 'preview') return;
        var k = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
        stage.__k = k;
        stage.style.transform = 'translate(' + ((window.innerWidth - 1920 * k) / 2).toFixed(1) + 'px,' + ((window.innerHeight - 1080 * k) / 2).toFixed(1) + 'px) scale(' + k + ')';
    }

    window.__seek = seek;
    window.__check = check;
    window.__ready = (document.fonts ? document.fonts.ready : Promise.resolve()).then(function () {
        return Promise.all(Array.prototype.map.call(document.images, function (img) {
            return img.decode ? img.decode().catch(function () {}) : null;
        }));
    }).then(function () { slides.forEach(prep); seek(0); return true; });

    if (MODE === 'preview') {
        fit();
        window.addEventListener('resize', function () { fit(); seek(lastT); });
        var lastT = 0;
        window.addEventListener('message', function (ev) {
            var d = ev.data || {};
            if (d.xv === 'seek') { lastT = +d.t || 0; seek(lastT); syncHost(lastT, !!d.playing); }
            else if (d.xv === 'check') {
                var issues = check();
                seek(lastT);
                parent.postMessage({ xv: 'checks', issues: issues }, '*');
            }
        });
        window.__ready.then(function () {
            parent.postMessage({ xv: 'ready', duration: DUR, start: +CFG.start || 0, end: CFG.end !== undefined ? +CFG.end : DUR,
                                 slides: slides.map(function (s) { return { id: s.el.id, t0: s.t0, t1: s.t1 }; }) }, '*');
        });
    }
})();
