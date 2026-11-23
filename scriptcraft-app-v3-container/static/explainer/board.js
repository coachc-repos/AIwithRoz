/* Board looks. Waves stay the default: this file does nothing then.
   Lettering uses Kalam Bold (OFL). Drawings are thick marker line art. */
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
    var OPS = film.ops || [];
    var KEYS = film.camera || [];
    var REGIONS = film.regions || [];

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
    function progOf(o, t) {
        var span = Math.max(0.08, (+o.t1 || 0) - (+o.t0 || 0));
        return ease(clamp((t - (+o.t0 || 0)) / span, 0, 1));
    }
    function round(ctx, x, y, w, h, r) {
        r = Math.max(0, Math.min(r, w / 2, h / 2));
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }

    var penTip = null;

    function drawBoard(ctx, cam, t) {
        var sky = ctx.createLinearGradient(0, 0, 1920, 1080);
        sky.addColorStop(0, PAL.board || '#f4f1ea');
        sky.addColorStop(1, PAL.board2 || PAL.board || '#e7e2d6');
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, 1920, 1080);
        if (LOOK === 'chalkboard') {
            ctx.fillStyle = PAL.wall || '#efe6d6';
            ctx.fillRect(0, 0, 1920, 1080);
            ctx.fillStyle = PAL.frame || '#6b4528';
            ctx.fillRect(28, 22, 1864, 1036);
            ctx.fillStyle = PAL.board || '#143328';
            ctx.fillRect(54, 46, 1812, 988);
            ctx.globalAlpha = 0.18;
            ctx.fillStyle = '#0c2418';
            for (var d = 0; d < 80; d++) {
                var dx = hash('cd' + d) * 1812 + 54, dy = hash('ce' + d) * 900 + 60;
                ctx.fillRect(dx, dy, 2, 2);
            }
            ctx.globalAlpha = 1;
        }
        if (LOOK === 'marker') {
            ctx.globalAlpha = 0.35;
            ctx.fillStyle = '#d9d3c6';
            for (var f = 0; f < 420; f++) {
                ctx.fillRect(hash('mf' + f) * 1920, hash('mg' + f) * 1080, 1.4, 1.4);
            }
            ctx.globalAlpha = 1;
        }
        if (INK.dots || LOOK === 'sketchnote') {
            ctx.fillStyle = PAL.ghost || '#e4e0d6';
            var step = 28 / Math.max(0.4, cam.z);
            var x0 = cam.x - 1100 / cam.z, y0 = cam.y - 700 / cam.z;
            for (var yy = Math.floor(y0 / step) * step; yy < cam.y + 700 / cam.z; yy += step) {
                for (var xx = Math.floor(x0 / step) * step; xx < cam.x + 1100 / cam.z; xx += step) {
                    var p = toScreen(xx, yy, cam);
                    if (p[0] < 0 || p[1] < 0 || p[0] > 1920 || p[1] > 1080) continue;
                    ctx.fillRect(p[0], p[1], 2.4, 2.4);
                }
            }
        }
        if (LOOK === 'whiteboard') {
            ctx.save();
            ctx.globalAlpha = 0.10;
            ctx.strokeStyle = PAL.ghost || '#8e97a6';
            ctx.fillStyle = PAL.ghost || '#8e97a6';
            ctx.lineWidth = 3;
            ctx.font = '42px Kalam, cursive';
            var ghosts = ['old lesson', '???', 'draft', 'erased'];
            for (var g = 0; g < ghosts.length; g++) {
                var gp = toScreen(80 + hash('gx' + g) * 1700, 80 + hash('gy' + g) * 860, cam);
                ctx.fillText(ghosts[g], gp[0], gp[1]);
            }
            ctx.beginPath();
            var c0 = toScreen(240, 700, cam), c1 = toScreen(520, 760, cam);
            ctx.arc((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2, 70 * cam.z, 0.2, 5.2);
            ctx.stroke();
            ctx.restore();
            var sheenX = ((cam.x * 0.35 + t * 24) % 2200) - 300;
            var sg = ctx.createLinearGradient(sheenX, 0, sheenX + 680, 1080);
            sg.addColorStop(0, 'rgba(255,255,255,0)');
            sg.addColorStop(0.45, 'rgba(255,255,255,0.22)');
            sg.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.fillStyle = sg;
            ctx.fillRect(0, 0, 1920, 1080);
        }
    }

    function worldBox(x, y, w, h, cam) {
        var a = toScreen(x, y, cam), b = toScreen(x + w, y + h, cam);
        return { x: a[0], y: a[1], w: b[0] - a[0], h: b[1] - a[1] };
    }

    function strokeRounded(ctx, box, width, color, prog) {
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.setLineDash([Math.max(8, box.w * 2 + box.h * 2), 8000]);
        ctx.lineDashOffset = (1 - prog) * (box.w * 2 + box.h * 2);
        round(ctx, box.x, box.y, box.w, box.h, Math.min(28, box.w * 0.08));
        ctx.stroke();
        ctx.restore();
    }

    function drawText(ctx, o, t, cam) {
        if (t < o.t0) return;
        var p = progOf(o, t);
        var at = toScreen(o.x, o.y, cam);
        var size = Math.max(12, o.size * cam.z);
        ctx.save();
        ctx.font = '700 ' + size.toFixed(1) + 'px Kalam, cursive';
        ctx.textBaseline = 'top';
        ctx.fillStyle = o.color || PAL.ink;
        ctx.strokeStyle = o.color || PAL.ink;
        ctx.lineWidth = Math.max(4, size * 0.045);
        ctx.lineJoin = 'round';
        var width = ctx.measureText(o.text).width;
        var grow = width * p + (p > 0.98 ? size * 0.12 : 0);
        ctx.beginPath();
        ctx.rect(at[0] - 4, at[1] - size * 0.15, Math.max(6, grow), size * 1.35);
        ctx.clip();
        if (LOOK !== 'chalkboard') {
            ctx.globalAlpha = 0.95;
        }
        ctx.strokeText(o.text, at[0], at[1]);
        ctx.fillText(o.text, at[0], at[1]);
        if (p > 0.04 && p < 0.99) {
            ctx.beginPath();
            ctx.arc(at[0] + width * p, at[1] + size * 0.72, Math.max(4, size * 0.08), 0, 6.283);
            ctx.fill();
        }
        ctx.restore();
        penTip = [at[0] + width * Math.min(1, p), at[1] + size * 0.75, p >= 0.999 ? 0.35 : 0, o.color];
    }

    function drawPhone(ctx, o, t, cam) {
        if (t < o.t0) return;
        var p = progOf(o, t);
        var box = worldBox(o.x, o.y, o.w, o.h, cam);
        var sw = Math.max(5, 7 * cam.z);
        ctx.save();
        if (p > 0.35) {
            ctx.globalAlpha = Math.min(1, (p - 0.35) / 0.3);
            ctx.fillStyle = o.fill || 'rgba(42,92,179,0.18)';
            round(ctx, box.x + sw, box.y + box.h * 0.08, box.w - sw * 2, box.h * 0.78, 12);
            ctx.fill();
            ctx.globalAlpha = 1;
        }
        strokeRounded(ctx, box, sw, o.color || PAL.ink, p);
        if (p > 0.55) {
            ctx.strokeStyle = o.color || PAL.ink;
            ctx.lineWidth = Math.max(4, 4 * cam.z);
            var y1 = box.y + box.h * 0.28, y2 = box.y + box.h * 0.42, y3 = box.y + box.h * 0.56;
            ctx.beginPath();
            ctx.moveTo(box.x + box.w * 0.18, y1); ctx.lineTo(box.x + box.w * 0.82, y1);
            ctx.moveTo(box.x + box.w * 0.18, y2); ctx.lineTo(box.x + box.w * 0.7, y2);
            ctx.moveTo(box.x + box.w * 0.18, y3); ctx.lineTo(box.x + box.w * 0.6, y3);
            ctx.stroke();
        }
        ctx.restore();
        if (o.magnet && p > 0.8 && INK.magnets) drawMagnet(ctx, box.x + box.w / 2, box.y - 8, cam, (p - 0.8) / 0.2);
    }

    function drawChart(ctx, o, t, cam) {
        if (t < o.t0) return;
        var p = progOf(o, t);
        var box = worldBox(o.x, o.y, o.w, o.h, cam);
        var sw = Math.max(5, 6 * cam.z);
        ctx.save();
        ctx.strokeStyle = o.color || PAL.ink;
        ctx.lineWidth = sw;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(box.x + 8, box.y + 10);
        ctx.lineTo(box.x + 8, box.y + box.h - 8);
        ctx.lineTo(box.x + box.w, box.y + box.h - 8);
        ctx.stroke();
        var bars = o.bars || [0.4, 0.6, 0.3, 0.9];
        var labels = o.labels || [];
        var gap = box.w / (bars.length + 0.4);
        ctx.font = '700 ' + Math.max(28, 56 * cam.z).toFixed(0) + 'px Kalam, cursive';
        ctx.textAlign = 'center';
        for (var i = 0; i < bars.length; i++) {
            var local = clamp((p * bars.length) - i, 0, 1);
            if (local <= 0) continue;
            var bh = (box.h - 36) * bars[i] * local;
            var x = box.x + gap * 0.6 + i * gap;
            var y = box.y + box.h - 14 - bh;
            var bw = gap * 0.55;
            ctx.fillStyle = i === bars.length - 1 ? (o.fill || PAL.accent) : 'rgba(35,38,44,0.18)';
            if (LOOK === 'chalkboard') ctx.fillStyle = i === bars.length - 1 ? (PAL.accent || '#e39b4a') : 'rgba(244,241,234,0.35)';
            ctx.fillRect(x, y, bw, bh);
            ctx.strokeStyle = o.color || PAL.ink;
            ctx.strokeRect(x, y, bw, bh);
            if (i === bars.length - 1 && local > 0.4) {
                ctx.save();
                ctx.beginPath();
                ctx.rect(x, y, bw, bh);
                ctx.clip();
                ctx.strokeStyle = PAL.ink || '#23262c';
                ctx.globalAlpha = 0.45;
                for (var hy = y; hy < y + bh; hy += 8) {
                    ctx.beginPath(); ctx.moveTo(x, hy); ctx.lineTo(x + bw, hy + 10); ctx.stroke();
                }
                ctx.restore();
            }
            if (labels[i] && local > 0.7) {
                ctx.fillStyle = o.color || PAL.ink;
                ctx.fillText(labels[i], x + bw / 2, box.y + box.h + 8);
            }
            if (o.magnet && i === bars.length - 1 && local > 0.85 && INK.magnets) {
                drawMagnet(ctx, x + bw / 2, y - 6, cam, (local - 0.85) / 0.15);
            }
        }
        ctx.restore();
    }

    function drawArrow(ctx, o, t, cam) {
        if (t < o.t0) return;
        var p = progOf(o, t);
        var a = toScreen(o.x1, o.y1, cam), b = toScreen(o.x2, o.y2, cam);
        var x = a[0] + (b[0] - a[0]) * p, y = a[1] + (b[1] - a[1]) * p;
        ctx.save();
        ctx.strokeStyle = o.color || PAL.accent;
        ctx.fillStyle = o.color || PAL.accent;
        ctx.lineWidth = Math.max(5, 7 * cam.z);
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(a[0], a[1]);
        ctx.lineTo(x, y);
        ctx.stroke();
        if (p > 0.75) {
            var ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
            var s = 16 * cam.z;
            ctx.beginPath();
            ctx.moveTo(b[0], b[1]);
            ctx.lineTo(b[0] - s * Math.cos(ang - 0.5), b[1] - s * Math.sin(ang - 0.5));
            ctx.lineTo(b[0] - s * Math.cos(ang + 0.5), b[1] - s * Math.sin(ang + 0.5));
            ctx.closePath();
            ctx.fill();
        }
        ctx.restore();
        penTip = [x, y, 0, o.color];
    }

    function drawChip(ctx, o, t, cam) {
        if (t < o.t0) return;
        var p = progOf(o, t);
        var box = worldBox(o.x, o.y, o.w, o.h, cam);
        ctx.save();
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = LOOK === 'sketchnote' ? 'rgba(31,138,138,0.28)' : 'rgba(42,92,179,0.12)';
        if (LOOK === 'marker') ctx.fillStyle = 'rgba(226,59,46,0.10)';
        if (LOOK === 'chalkboard') ctx.fillStyle = 'rgba(244,241,234,0.12)';
        round(ctx, box.x, box.y, box.w * p, box.h, 16);
        ctx.fill();
        strokeRounded(ctx, box, Math.max(4, 5 * cam.z), o.color || PAL.ink, p);
        ctx.restore();
        if (p > 0.45) drawText(ctx, { text: o.text, x: o.x + 16, y: o.y + 10, size: 54, color: o.color, t0: o.t0, t1: o.t1 }, t, cam);
    }

    function drawStep(ctx, o, t, cam) {
        if (t < o.t0) return;
        var p = progOf(o, t);
        var c = toScreen(o.x, o.y, cam);
        var r = Math.max(18, 28 * cam.z);
        ctx.save();
        ctx.fillStyle = o.fill || PAL.accent;
        ctx.strokeStyle = o.color || PAL.ink;
        ctx.lineWidth = Math.max(4, 4 * cam.z);
        ctx.beginPath();
        ctx.arc(c[0], c[1], r, 0, 6.283 * p);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = LOOK === 'chalkboard' ? '#143328' : '#fffaf3';
        ctx.font = '700 ' + Math.max(20, 26 * cam.z).toFixed(0) + 'px Kalam, cursive';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        if (p > 0.4) ctx.fillText(String(o.n), c[0], c[1] + 1);
        ctx.restore();
        if (o.label) drawText(ctx, { text: o.label, x: o.x + 52, y: o.y - 26, size: 52, color: o.color || PAL.ink, t0: o.t0 + 0.05, t1: o.t1 }, t, cam);
    }

    function drawCallout(ctx, o, t, cam) {
        if (t < o.t0) return;
        var box = worldBox(o.x, o.y, 180, 78, cam);
        strokeRounded(ctx, box, Math.max(4, 5 * cam.z), o.color || PAL.accent, progOf(o, t));
        drawText(ctx, { text: o.text, x: o.x + 28, y: o.y + 12, size: 48, color: o.color, t0: o.t0, t1: o.t1 }, t, cam);
    }

    function drawPlate(ctx, o, t, cam) {
        if (t < o.t0) return;
        var p = progOf(o, t);
        var box = worldBox(o.x, o.y, o.w * p, o.h, cam);
        ctx.save();
        ctx.fillStyle = o.color || 'rgba(42,92,179,0.08)';
        round(ctx, box.x, box.y, box.w, box.h, 28);
        ctx.fill();
        ctx.strokeStyle = PAL.ink || '#23262c';
        ctx.globalAlpha = 0.35;
        ctx.lineWidth = Math.max(4, 5 * cam.z);
        ctx.stroke();
        ctx.restore();
    }

    function drawMagnet(ctx, sx, sy, cam, u) {
        var lift = (1 - clamp(u, 0, 1)) * 28;
        ctx.save();
        ctx.fillStyle = 'rgba(0,0,0,0.30)';
        ctx.beginPath();
        ctx.ellipse(sx + 8, sy + 26 + lift, 34 * cam.z, 10 * cam.z, 0, 0, 6.283);
        ctx.fill();
        var w = 54 * cam.z, h = 34 * cam.z;
        ctx.fillStyle = '#f7f7f8';
        ctx.strokeStyle = PAL.accent || '#d97757';
        ctx.lineWidth = Math.max(3, 4 * cam.z);
        round(ctx, sx - w / 2, sy - h - lift, w, h, 8);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = PAL.accent || '#d97757';
        ctx.fillRect(sx - w / 2, sy - h - lift, w, h * 0.32);
        ctx.restore();
    }

    function drawPen(ctx) {
        if (!INK.pen || !penTip) return;
        var x = penTip[0], y = penTip[1], lift = penTip[2] || 0, color = penTip[3] || PAL.accent;
        if (lift > 0.95) return;
        ctx.save();
        ctx.fillStyle = 'rgba(20,20,20,0.35)';
        ctx.beginPath();
        ctx.ellipse(x + 16, y + 36 + lift * 22, 22 + lift * 12, 8 + lift * 5, 0, 0, 6.283);
        ctx.fill();
        ctx.translate(x, y - lift * 30);
        ctx.rotate(-0.7);
        ctx.fillStyle = '#f4f4f5';
        round(ctx, -9, -58, 18, 78, 8);
        ctx.fill();
        ctx.fillStyle = color;
        ctx.fillRect(-9, -58, 18, 20);
        ctx.fillStyle = '#222';
        ctx.beginPath();
        ctx.moveTo(-5, 20); ctx.lineTo(5, 20); ctx.lineTo(0, 36); ctx.closePath();
        ctx.fill();
        ctx.restore();
    }

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
        if (!(cam.z > 0.2)) cam = { x: cam.x || 960, y: cam.y || 540, z: 1 };
        penTip = null;
        drawBoard(ctx, cam, t);
        for (var i = 0; i < OPS.length; i++) {
            var o = OPS[i];
            if (t + 0.02 < o.t0) continue;
            if (o.op === 'plate') drawPlate(ctx, o, t, cam);
            else if (o.op === 'text') drawText(ctx, o, t, cam);
            else if (o.op === 'phone') drawPhone(ctx, o, t, cam);
            else if (o.op === 'chart') drawChart(ctx, o, t, cam);
            else if (o.op === 'arrow') drawArrow(ctx, o, t, cam);
            else if (o.op === 'chip') drawChip(ctx, o, t, cam);
            else if (o.op === 'step') drawStep(ctx, o, t, cam);
            else if (o.op === 'callout') drawCallout(ctx, o, t, cam);
        }
        if (!OPS.length && REGIONS.length) {
            ctx.fillStyle = PAL.ink || '#23262c';
            ctx.font = '700 72px Kalam, cursive';
            var r0 = REGIONS[0];
            var at = toScreen(r0.x + 80, r0.y + 120, cam);
            ctx.fillText('Next token', at[0], at[1]);
        }
        drawPen(ctx);
    }

    window.XVBoard.paint = paint;
    window.XVBoard.cameraAt = cameraAt;
    window.XVBoard.ease = ease;
})();
