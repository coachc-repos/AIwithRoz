/* Board looks for the explainer. Original canvas drawing.
   Waves stay the default: when the look is waves this file does nothing.
   Whiteboard, chalkboard, sketchnote and marker-on-paper share one camera,
   one stroke writer and one set of line-art objects. */
(function () {
    'use strict';
    var CFG = window.__EXPLAINER || {};
    var film = CFG.film || { look: 'waves' };
    var LOOK = film.look || 'waves';
    var ON = LOOK === 'whiteboard' || LOOK === 'chalkboard' || LOOK === 'sketchnote' || LOOK === 'marker';
    window.XVBoard = { on: ON, ink: (film.palette || {}).emphasis || '' };
    if (!ON) return;

    var PAL = film.palette || {};
    var INK = film.ink || {};
    var GLYPHS = film.glyphs || {};
    var LETTERS = film.letters || [];
    var REGIONS = film.regions || [];
    var OBJECTS = [];
    REGIONS.forEach(function (r) {
        (r.objects || []).forEach(function (o) { o.region = r.i; OBJECTS.push(o); });
    });
    var KEYS = film.camera || [];
    var NATIVE = film.native || [];

    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function ease(u) {
        u = clamp(u, 0, 1);
        return u - Math.sin(2 * Math.PI * u) / (2 * Math.PI) * 0.8;
    }
    function camEase(p) { p = clamp(p, 0, 1); return p * p * (3 - 2 * p); }
    function hash(s) {
        var h = 2166136261;
        s = String(s);
        for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
        return (h >>> 0) / 4294967295;
    }
    function cameraAt(t) {
        if (!KEYS.length) return { x: 960, y: 540, z: 1 };
        if (t <= KEYS[0].t) return KEYS[0];
        if (t >= KEYS[KEYS.length - 1].t) return KEYS[KEYS.length - 1];
        for (var i = 0; i < KEYS.length - 1; i++) {
            var a = KEYS[i], b = KEYS[i + 1];
            if (t >= a.t && t <= b.t) {
                var p = camEase((t - a.t) / Math.max(1e-4, b.t - a.t));
                return { x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p, z: a.z + (b.z - a.z) * p };
            }
        }
        return KEYS[KEYS.length - 1];
    }
    function toScreen(x, y, cam) {
        return [960 + (x - cam.x) * cam.z, 540 + (y - cam.y) * cam.z];
    }
    function regionAt(t) {
        var best = REGIONS[0] || null;
        for (var i = 0; i < REGIONS.length; i++) {
            if (t >= REGIONS[i].t0 - 0.02) best = REGIONS[i];
        }
        return best;
    }
    function nativeAt(t) {
        for (var i = 0; i < NATIVE.length; i++) {
            var e = NATIVE[i];
            if (t >= e.t && t < e.t + e.dur) return e;
        }
        return null;
    }
    function alive(region, t, fx) {
        if (!region) return false;
        if (LOOK === 'marker') {
            var cur = regionAt(t);
            return cur && region.i === cur.i;
        }
        if (LOOK === 'chalkboard') {
            var now = regionAt(t);
            if (!now || region.i !== now.i && region.i !== now.i - 1) return false;
            if (fx && fx.style === 'wipe' && region.i < now.i) return true;
            return region.i === now.i;
        }
        return t >= region.t0 - 0.05;
    }

    function glyph(ch) {
        if (GLYPHS[ch]) return GLYPHS[ch];
        var up = String(ch || '').toUpperCase();
        if (GLYPHS[up]) return GLYPHS[up];
        return GLYPHS['?'];
    }

    var ICONS = {
        phone: ['0.28,0.04 0.72,0.04 0.78,0.10 0.78,0.90 0.72,0.96 0.28,0.96 0.22,0.90 0.22,0.10 0.28,0.04',
                '0.38,0.10 0.62,0.10', '0.46,0.88 0.54,0.88'],
        chart: ['0.08,0.88 0.92,0.88', '0.08,0.88 0.08,0.10',
                '0.22,0.70 0.22,0.40', '0.40,0.70 0.40,0.28', '0.58,0.70 0.58,0.48', '0.76,0.70 0.76,0.18'],
        house: ['0.08,0.48 0.50,0.12 0.92,0.48', '0.18,0.48 0.18,0.90 0.82,0.90 0.82,0.48', '0.42,0.90 0.42,0.66 0.58,0.66 0.58,0.90'],
        car: ['0.08,0.62 0.22,0.42 0.62,0.38 0.78,0.52 0.94,0.58 0.94,0.74 0.08,0.74 0.08,0.62',
              '0.28,0.74 0.28,0.74', '0.72,0.74 0.72,0.74'],
        tree: ['0.50,0.92 0.50,0.48', '0.18,0.52 0.50,0.08 0.82,0.52 0.18,0.52'],
        building: ['0.12,0.92 0.12,0.16 0.88,0.16 0.88,0.92', '0.28,0.32 0.28,0.44', '0.48,0.32 0.48,0.44', '0.68,0.32 0.68,0.44',
                   '0.28,0.56 0.28,0.68', '0.48,0.56 0.48,0.68', '0.68,0.56 0.68,0.68'],
        datacenter: ['0.06,0.30 0.94,0.30 0.94,0.92 0.06,0.92 0.06,0.30', '0.14,0.42 0.86,0.42', '0.14,0.56 0.86,0.56', '0.14,0.70 0.86,0.70'],
        factory: ['0.04,0.92 0.04,0.48 0.46,0.48 0.46,0.28 0.78,0.48 0.96,0.48 0.96,0.92', '0.58,0.28 0.58,0.08 0.70,0.08 0.70,0.28'],
        server: ['0.22,0.06 0.78,0.06 0.78,0.96 0.22,0.96 0.22,0.06', '0.32,0.22 0.68,0.22', '0.32,0.40 0.68,0.40', '0.32,0.58 0.68,0.58'],
        powerline: ['0.08,0.92 0.08,0.20', '0.92,0.92 0.92,0.20', '0.08,0.28 0.50,0.48 0.92,0.28'],
        brand: ['0.12,0.12 0.88,0.12 0.88,0.88 0.12,0.88 0.12,0.12'],
        bot: ['0.20,0.28 0.80,0.28 0.86,0.50 0.80,0.78 0.20,0.78 0.14,0.50 0.20,0.28', '0.36,0.46 0.36,0.46', '0.64,0.46 0.64,0.46']
    };

    function parsePoly(spec) {
        return spec.split(' ').map(function (pair) {
            var xy = pair.split(',');
            return [parseFloat(xy[0]), parseFloat(xy[1])];
        });
    }

    function wobblePoint(x, y, nx, ny, seed, amp) {
        return [x + nx * amp * Math.sin(seed), y + ny * amp * Math.sin(seed + 1.7)];
    }

    function drawRibbon(ctx, pts, width, color, prog, seed, cam) {
        if (!pts || pts.length < 2 || prog <= 0) return null;
        var lengths = [0], total = 0;
        for (var i = 1; i < pts.length; i++) {
            var dx = pts[i][0] - pts[i - 1][0], dy = pts[i][1] - pts[i - 1][1];
            total += Math.sqrt(dx * dx + dy * dy);
            lengths.push(total);
        }
        if (!(total > 0.5)) return null;
        var over = (INK.overshoot || 0) * width;
        var want = total * prog + (prog >= 0.999 ? over : 0);
        var out = [pts[0]];
        for (var k = 1; k < pts.length; k++) {
            if (lengths[k] <= want) { out.push(pts[k]); continue; }
            var seg = Math.max(1e-4, lengths[k] - lengths[k - 1]);
            var f = (want - lengths[k - 1]) / seg;
            out.push([pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * f,
                      pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * f]);
            break;
        }
        if (out.length < 2) return null;
        ctx.save();
        if (INK.multiply && LOOK !== 'chalkboard') ctx.globalCompositeOperation = 'multiply';
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.lineWidth = Math.max(1.4, width);
        ctx.globalAlpha = LOOK === 'chalkboard' ? 0.92 : 0.94;
        ctx.beginPath();
        var started = false;
        for (var p = 1; p < out.length; p++) {
            var ax = out[p - 1][0], ay = out[p - 1][1], bx = out[p][0], by = out[p][1];
            var vx = bx - ax, vy = by - ay;
            var len = Math.sqrt(vx * vx + vy * vy) || 1;
            var nx = -vy / len, ny = vx / len;
            var amp = LOOK === 'marker' ? width * 0.04 : width * 0.16;
            if (LOOK === 'chalkboard') amp = width * 0.05;
            var a = wobblePoint(ax, ay, nx, ny, seed + p * 0.7, amp);
            var b = wobblePoint(bx, by, nx, ny, seed + p * 0.7 + 0.4, amp);
            if (INK.dry && ((seed * 13 + p) % 7 === 2)) {
                started = false;
                continue;
            }
            if (!started) { ctx.moveTo(a[0], a[1]); started = true; }
            ctx.lineTo(b[0], b[1]);
        }
        ctx.stroke();
        if (INK.pool && prog > 0.02 && total > width * 6) {
            ctx.globalAlpha = 0.55;
            ctx.beginPath();
            ctx.arc(out[0][0], out[0][1], width * 0.42, 0, 6.283);
            ctx.fill();
        }
        if (INK.chalk && prog > 0.05) {
            ctx.globalCompositeOperation = 'source-over';
            ctx.globalAlpha = 0.35;
            var tip = out[out.length - 1];
            for (var g = 0; g < 4; g++) {
                var ang = hash(seed + ':' + g) * 6.28;
                var rad = width * (0.4 + hash(seed + 'r' + g));
                ctx.fillRect(tip[0] + Math.cos(ang) * rad, tip[1] + Math.sin(ang) * rad, 1.6, 1.6);
            }
        }
        ctx.restore();
        return out[out.length - 1];
    }

    function drawGlyphStroke(ctx, letter, strokeIndex, t, cam) {
        var g = glyph(letter.ch);
        if (!g || !g.s || !g.s[strokeIndex]) return null;
        var st = letter.strokes[strokeIndex];
        if (!st) return null;
        var prog = ease(clamp((t - st.t0) / Math.max(0.02, st.t1 - st.t0), 0, 1));
        if (t < st.t0) return null;
        var src = g.s[strokeIndex];
        var pts = src.map(function (pt) {
            var wx = letter.x + pt[0] * letter.size * 0.62;
            var wy = letter.y + pt[1] * letter.size;
            return toScreen(wx, wy, cam);
        });
        var width = letter.size * (LOOK === 'marker' ? 0.11 : LOOK === 'sketchnote' ? 0.045 : LOOK === 'chalkboard' ? 0.07 : 0.075) * cam.z;
        return drawRibbon(ctx, pts, width, letter.color, t >= st.t1 ? 1 : prog, hash(letter.ch + letter.x + strokeIndex), cam);
    }

    function drawIcon(ctx, obj, t, cam) {
        var spec = ICONS[obj.name] || ICONS.brand;
        var span = Math.max(0.2, (obj.t1 || obj.t0 + 0.8) - obj.t0);
        var u = clamp((t - obj.t0) / span, 0, 1);
        var drawn = 0;
        var total = spec.length;
        var tip = null;
        spec.forEach(function (poly, i) {
            var a = i / total, b = (i + 1) / total;
            var prog = clamp((u - a) / Math.max(1e-4, b - a), 0, 1);
            if (prog <= 0) return;
            var pts = parsePoly(poly).map(function (pt) {
                return toScreen(obj.x + pt[0] * obj.w, obj.y + pt[1] * obj.h, cam);
            });
            var width = (LOOK === 'marker' ? 8 : LOOK === 'sketchnote' ? 3.2 : 5.5) * cam.z * (obj.w / 220);
            width = clamp(width, 1.6, 16);
            var color = LOOK === 'marker' && i === spec.length - 1 ? (PAL.accent || '#e23b2e') : (PAL.ink || '#23262c');
            tip = drawRibbon(ctx, pts, width, color, prog, hash(obj.name + i + obj.x), cam) || tip;
            drawn++;
        });
        if (obj.label && u > 0.7) {
            ctx.save();
            ctx.fillStyle = PAL.ink || '#23262c';
            ctx.globalAlpha = Math.min(1, (u - 0.7) / 0.3);
            ctx.font = Math.round(28 * cam.z) + 'px sans-serif';
            var at = toScreen(obj.x + obj.w * 0.5, obj.y + obj.h + 36, cam);
            ctx.textAlign = 'center';
            ctx.fillText(obj.label, at[0], at[1]);
            ctx.restore();
        }
        if (obj.magnet && u > 0.85 && INK.magnets) drawMagnet(ctx, obj, cam, (u - 0.85) / 0.15);
        return tip;
    }

    function drawMagnet(ctx, obj, cam, u) {
        var lift = (1 - clamp(u, 0, 1)) * 36;
        var c = toScreen(obj.x + obj.w * 0.5, obj.y - 28 - lift, cam);
        var s = toScreen(obj.x + obj.w * 0.5, obj.y + 8, cam);
        ctx.save();
        ctx.fillStyle = 'rgba(0,0,0,0.28)';
        ctx.beginPath();
        ctx.ellipse(s[0], s[1], 26 * cam.z, 8 * cam.z, 0, 0, 6.283);
        ctx.fill();
        ctx.fillStyle = '#f4f4f6';
        ctx.strokeStyle = PAL.accent || '#d97757';
        ctx.lineWidth = Math.max(2, 4 * cam.z);
        var w = 34 * cam.z, h = 22 * cam.z;
        round(ctx, c[0] - w / 2, c[1] - h / 2, w, h, 6 * cam.z);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = PAL.accent || '#d97757';
        ctx.fillRect(c[0] - w / 2, c[1] - h / 2, w, h * 0.28);
        ctx.restore();
    }

    function round(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }

    function drawPen(ctx, tip, lift, color) {
        if (!INK.pen || !tip) return;
        var x = tip[0], y = tip[1] - lift * 26;
        if (lift > 0.92) return;
        ctx.save();
        ctx.fillStyle = 'rgba(30,30,30,0.28)';
        ctx.beginPath();
        ctx.ellipse(x + 10, y + 28 + lift * 18, 16 + lift * 10, 6 + lift * 4, 0, 0, 6.283);
        ctx.fill();
        ctx.translate(x, y);
        ctx.rotate(-0.7);
        ctx.fillStyle = '#f7f7f8';
        round(ctx, -7, -46, 14, 62, 6);
        ctx.fill();
        ctx.fillStyle = color || PAL.accent || '#d97757';
        ctx.fillRect(-7, -46, 14, 16);
        ctx.fillStyle = '#2a2a2e';
        ctx.beginPath();
        ctx.moveTo(-4, 16); ctx.lineTo(4, 16); ctx.lineTo(0, 28); ctx.closePath();
        ctx.fill();
        ctx.restore();
    }

    function drawBoard(ctx, cam, t) {
        var g = ctx.createLinearGradient(0, 0, 1920, 1080);
        g.addColorStop(0, PAL.board || '#f3f0e8');
        g.addColorStop(1, PAL.board2 || PAL.board || '#e4ddd0');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, 1920, 1080);
        if (LOOK === 'chalkboard') {
            ctx.fillStyle = PAL.wall || '#efe6d6';
            ctx.fillRect(0, 0, 1920, 1080);
            var slate = REGIONS[0];
            if (slate) {
                var a = toScreen(slate.x - 70, slate.y - 70, cam);
                var b = toScreen(slate.x + slate.w + 70, slate.y + slate.h + 90, cam);
                ctx.fillStyle = PAL.frame || '#6b4528';
                ctx.fillRect(a[0] - 28, a[1] - 28, (b[0] - a[0]) + 56, (b[1] - a[1]) + 56);
                ctx.fillStyle = PAL.board || '#143328';
                ctx.fillRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
            }
        }
        if (INK.dots) {
            ctx.fillStyle = PAL.ghost || '#e4e0d6';
            var step = 46;
            var x0 = Math.floor((cam.x - 1100 / cam.z) / step) * step;
            var y0 = Math.floor((cam.y - 700 / cam.z) / step) * step;
            for (var yy = y0; yy < cam.y + 700 / cam.z; yy += step) {
                for (var xx = x0; xx < cam.x + 1100 / cam.z; xx += step) {
                    var p = toScreen(xx, yy, cam);
                    if (p[0] < -4 || p[1] < -4 || p[0] > 1924 || p[1] > 1084) continue;
                    ctx.fillRect(p[0], p[1], 2.2, 2.2);
                }
            }
        }
        if (LOOK === 'whiteboard') {
            ctx.save();
            ctx.globalAlpha = 0.07;
            ctx.strokeStyle = PAL.ghost || '#8e97a6';
            ctx.lineWidth = 2;
            for (var n = 0; n < 18; n++) {
                var gx = (hash('gx' + n) * 6400);
                var gy = (hash('gy' + n) * 3600);
                var pa = toScreen(gx, gy, cam), pb = toScreen(gx + 80 + hash('gl' + n) * 140, gy + (hash('gh' + n) - 0.5) * 40, cam);
                ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke();
            }
            ctx.restore();
            var sheenX = (cam.x * 0.35 + t * 18) % 2400 - 400;
            var sg = ctx.createLinearGradient(sheenX, 0, sheenX + 520, 1080);
            sg.addColorStop(0, 'rgba(255,255,255,0)');
            sg.addColorStop(0.5, 'rgba(255,255,255,0.14)');
            sg.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.fillStyle = sg;
            ctx.fillRect(0, 0, 1920, 1080);
        }
    }

    function drawBanner(ctx, region, t, cam) {
        if (LOOK !== 'sketchnote') return;
        (region.lines || []).forEach(function (line) {
            if (!line.banner || !line.words || !line.words.length) return;
            var start = line.words[0].t0;
            var u = clamp((t - start + 0.25) / 0.45, 0, 1);
            if (u <= 0) return;
            var x0 = region.x + 70, y0 = line.y - 16, w = Math.min(region.w * 0.7, 900) * u, h = line.size + 28;
            var a = toScreen(x0, y0, cam), b = toScreen(x0 + w, y0 + h, cam);
            ctx.save();
            ctx.globalCompositeOperation = 'multiply';
            ctx.fillStyle = 'rgba(226,176,0,0.55)';
            round(ctx, a[0], a[1], b[0] - a[0], b[1] - a[1], 14 * cam.z);
            ctx.fill();
            ctx.restore();
        });
    }

    function drawPageNo(ctx, region, cam) {
        if (LOOK !== 'marker' || !region) return;
        var c = toScreen(region.x + region.w - 120, region.y + 70, cam);
        ctx.save();
        ctx.strokeStyle = PAL.ink || '#1b1c20';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(c[0], c[1], 22 * cam.z, 0, 6.283);
        ctx.stroke();
        ctx.fillStyle = PAL.ink || '#1b1c20';
        ctx.font = Math.round(22 * cam.z) + 'px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(region.i + 1), c[0], c[1]);
        ctx.restore();
    }

    function wipeBand(ctx, fx, t) {
        var p = clamp((t - fx.t) / Math.max(0.05, fx.dur), 0, 1);
        ctx.save();
        ctx.fillStyle = LOOK === 'chalkboard' ? (PAL.board || '#143328') : 'rgba(243,240,232,0.92)';
        ctx.fillRect(0, 0, 1920 * p, 1080);
        ctx.restore();
    }

    function peel(ctx, fx, t) {
        var p = clamp((t - fx.t) / Math.max(0.05, fx.dur), 0, 1);
        ctx.save();
        ctx.fillStyle = 'rgba(70,63,51,0.16)';
        ctx.beginPath();
        ctx.moveTo(1920, 1080);
        ctx.lineTo(1920 - 1400 * p, 1080);
        ctx.lineTo(1920, 1080 - 900 * p);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
    }

    var penTip = null;

    function paint(ctx, canvas, t) {
        var k = window.devicePixelRatio || 1;
        if (canvas.width !== 1920 * k || canvas.height !== 1080 * k) {
            canvas.width = 1920 * k;
            canvas.height = 1080 * k;
            canvas.style.width = '1920px';
            canvas.style.height = '1080px';
        }
        ctx.setTransform(k, 0, 0, k, 0, 0);
        var cam = cameraAt(t);
        var fx = nativeAt(t);
        drawBoard(ctx, cam, t);
        penTip = null;
        var lift = 1;
        REGIONS.forEach(function (region) {
            if (!alive(region, t, fx)) return;
            if (LOOK === 'chalkboard' && fx && fx.style === 'wipe' && region.i < regionAt(t).i) {
                var p = clamp((t - fx.t) / Math.max(0.05, fx.dur), 0, 1);
                ctx.save();
                ctx.beginPath();
                ctx.rect(1920 * p, 0, 1920, 1080);
                ctx.clip();
            }
            drawBanner(ctx, region, t, cam);
            if (LOOK === 'chalkboard' && fx && fx.style === 'wipe' && region.i < regionAt(t).i) ctx.restore();
        });
        LETTERS.forEach(function (letter) {
            var region = REGIONS[letter.region];
            if (!alive(region, t, fx)) return;
            if (LOOK === 'chalkboard' && fx && fx.style === 'wipe' && region && region.i < regionAt(t).i) {
                var keep = 1920 * clamp((t - fx.t) / Math.max(0.05, fx.dur), 0, 1);
                var at = toScreen(letter.x, letter.y, cam);
                if (at[0] < keep) return;
            }
            for (var s = 0; s < (letter.strokes || []).length; s++) {
                var tip = drawGlyphStroke(ctx, letter, s, t, cam);
                var st = letter.strokes[s];
                if (t >= st.t0 && t <= st.t1 + 0.12) {
                    penTip = tip || penTip;
                    lift = t <= st.t1 ? 0 : clamp((t - st.t1) / 0.35, 0, 1);
                }
            }
        });
        OBJECTS.forEach(function (obj) {
            var region = REGIONS[obj.region];
            if (!alive(region, t, fx)) return;
            if (t + 0.02 < obj.t0) return;
            drawIcon(ctx, obj, t, cam);
        });
        REGIONS.forEach(function (region) {
            if (regionAt(t) && region.i === regionAt(t).i) drawPageNo(ctx, region, cam);
        });
        if (fx && fx.style === 'wipe') wipeBand(ctx, fx, t);
        if (fx && fx.style === 'peel') peel(ctx, fx, t);
        if (!fx) drawPen(ctx, penTip, lift, (PAL.accent || PAL.ink));
    }

    window.XVBoard.paint = paint;
    window.XVBoard.cameraAt = cameraAt;
    window.XVBoard.ease = ease;
})();
