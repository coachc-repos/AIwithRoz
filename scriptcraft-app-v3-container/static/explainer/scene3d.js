/* Original 3D looks, drawn one frame at a time with Three.js r149 (MIT).
   Tilt-shift miniature, low-poly island, tabletop flythrough, paper pop-up.
   Not derived from Lemo-Opuscar code or assets. */
(function () {
    'use strict';
    var T = window.THREE;
    var CFG = window.__EXPLAINER || {};
    var film = CFG.film || {};
    var LOOK = film.look || '';
    var ON = LOOK === 'tilt' || LOOK === 'island' || LOOK === 'tabletop' || LOOK === 'popup';
    window.XVBoard = window.XVBoard || { on: false };
    if (!ON || !T) {
        if (ON) window.__err = 'THREE missing';
        return;
    }
    window.XVBoard.on = true;
    window.XVBoard.mode = '3d';
    window.XVBoard.ink = LOOK === 'island' ? '#f2c14e' : '#e23b2e';

    var pack = null;
    var bars = [];
    var wheels = [];
    var car = null;
    var hinges = [];
    var phone = null;
    var chart = null;
    var chips = null;
    var titles = [];
    var solids = [];

    function ease(t, a, b) {
        var u = Math.max(0, Math.min(1, (t - a) / Math.max(0.001, b - a)));
        return u * u * (3 - 2 * u);
    }
    function mat(color, rough, metal, flat) {
        var m = new T.MeshStandardMaterial({
            color: color,
            roughness: rough == null ? 0.6 : rough,
            metalness: metal || 0,
            flatShading: !!flat
        });
        return m;
    }
    function paperMat(hex) {
        var c = document.createElement('canvas');
        c.width = 64;
        c.height = 64;
        var g = c.getContext('2d');
        g.fillStyle = hex;
        g.fillRect(0, 0, 64, 64);
        g.fillStyle = 'rgba(70,50,30,0.09)';
        for (var i = 0; i < 180; i++) g.fillRect((i * 17) % 64, (i * 29) % 64, 1, 2);
        var tex = new T.CanvasTexture(c);
        return new T.MeshStandardMaterial({ map: tex, roughness: 0.95, metalness: 0, color: 0xffffff });
    }
    function add(geo, material, x, y, z, parent) {
        var m = new T.Mesh(geo, material);
        m.position.set(x, y, z);
        m.castShadow = true;
        m.receiveShadow = true;
        parent.add(m);
        return m;
    }
    function box(w, h, d, color, x, y, z, parent, flat) {
        return add(new T.BoxGeometry(w, h, d), mat(color, flat ? 0.85 : 0.55, 0, flat), x, y, z, parent);
    }

    function makePhone(color, screen, parent) {
        var g = new T.Group();
        box(0.82, 1.68, 0.12, color, 0, 0, 0, g);
        box(0.68, 1.40, 0.04, screen, 0, 0.02, 0.07, g);
        box(0.28, 0.08, 0.04, color, 0, 0.62, 0.09, g);
        parent.add(g);
        return g;
    }
    function makeCar(color, parent) {
        var g = new T.Group();
        box(2.45, 0.46, 1.05, color, 0.05, 0.50, 0, g);
        box(1.20, 0.40, 0.92, color, -0.02, 0.88, 0, g);
        var local = [];
        [[-0.78, 0.32, 0.50], [0.78, 0.32, 0.50], [-0.78, 0.32, -0.50], [0.78, 0.32, -0.50]].forEach(function (p) {
            var w = new T.Mesh(new T.CylinderGeometry(0.32, 0.32, 0.22, 18), mat(0x23262e, 0.7, 0.05));
            w.geometry.rotateZ(Math.PI / 2);
            w.position.set(p[0], p[1], p[2]);
            w.castShadow = true;
            g.add(w);
            local.push(w);
        });
        parent.add(g);
        return { group: g, wheels: local };
    }
    function makeHouse(wall, roof, parent, flat) {
        var g = new T.Group();
        box(1.5, 1.1, 1.25, wall, 0, 0.55, 0, g, flat);
        var top = new T.Mesh(new T.ConeGeometry(1.15, 0.7, flat ? 4 : 4), mat(roof, 0.8, 0, flat));
        top.position.y = 1.28;
        top.rotation.y = Math.PI / 4;
        top.castShadow = true;
        g.add(top);
        box(0.28, 0.42, 0.06, 0xf2cc8f, 0, 0.42, 0.62, g, flat);
        parent.add(g);
        return g;
    }
    function makeCity(color, parent, flat) {
        var g = new T.Group();
        [0.7, 1.25, 0.95, 1.55, 0.8].forEach(function (h, i) {
            var b = box(0.48, h, 0.48, color, i * 0.62, h / 2, 0, g, flat);
            if (LOOK === 'island') b.material.emissive = new T.Color(0xf2c14e);
            if (LOOK === 'island') b.material.emissiveIntensity = 0.18;
        });
        parent.add(g);
        return g;
    }
    function makeChart(barColor, win, parent, flat) {
        var g = new T.Group();
        box(3.1, 0.08, 0.9, LOOK === 'popup' ? 0xf6efe2 : 0xd9d3c4, 0, 0.04, 0, g, flat);
        var heights = [0.7, 1.15, 0.5, 1.85];
        var names = ['a', 'the', 'on', 'mat'];
        var made = heights.map(function (h, i) {
            var b = box(0.42, h, 0.42, i === 3 ? win : barColor, -1.05 + i * 0.7, h / 2 + 0.08, 0, g, flat);
            b.userData.full = h;
            b.userData.label = names[i];
            b.scale.y = 0.04;
            b.position.y = 0.1;
            return b;
        });
        parent.add(g);
        return { group: g, bars: made };
    }
    function makeChips(color, parent, flat) {
        var g = new T.Group();
        ['The', 'cat', 'sat', 'on'].forEach(function (word, i) {
            var chip = box(0.7, 0.46, 0.28, color, i * 0.84, 0.23, 0, g, flat);
            chip.userData.label = word;
        });
        parent.add(g);
        return g;
    }

    function build() {
        var scene = new T.Scene();
        var persp = new T.PerspectiveCamera(32, 1920 / 1080, 0.08, 80);
        var ortho = new T.OrthographicCamera(-7.2, 7.2, 4.05, -4.05, 0.1, 80);
        var renderer = new T.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
        renderer.setSize(1920, 1080, false);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = T.PCFSoftShadowMap;
        if (T.sRGBEncoding) renderer.outputEncoding = T.sRGBEncoding;
        var gl = renderer.domElement;

        var key = new T.DirectionalLight(0xfff4e4, 1.15);
        key.position.set(-4, 9, 6);
        key.castShadow = true;
        key.shadow.mapSize.set(1024, 1024);
        key.shadow.camera.near = 0.5;
        key.shadow.camera.far = 30;
        key.shadow.camera.left = -10;
        key.shadow.camera.right = 10;
        key.shadow.camera.top = 10;
        key.shadow.camera.bottom = -10;
        scene.add(key);
        scene.add(new T.AmbientLight(0xffffff, 0.35));

        if (LOOK === 'tilt') {
            scene.background = new T.Color(0x8fd0f2);
            scene.add(new T.HemisphereLight(0xbfe6ff, 0x3d8f4a, 0.45));
            var ground = box(16, 0.4, 11, 0x2fbe5a, 0, -0.2, 0, scene);
            ground.receiveShadow = true;
            box(16, 0.06, 1.5, 0x5b616c, 0, 0.04, 1.15, scene);
            phone = makePhone(0xff5a36, 0x1d3f8a, scene);
            phone.position.set(-2.4, 0.84, 0.15);
            solids.push(phone);
            chips = makeChips(0xffe08a, scene);
            chips.position.set(-4.3, 0, -0.85);
            var built = makeCar(0x2456d6, scene);
            car = built.group;
            wheels = built.wheels;
            car.position.set(0.6, 0, 1.15);
            solids.push(car, chips);
            solids.push(makeHouse(0xfff3df, 0xe23b2e, scene));
            solids[solids.length - 1].position.set(-0.2, 0, -2.3);
            solids.push(makeCity(0xf4f1de, scene));
            solids[solids.length - 1].position.set(2.4, 0, -2.5);
            var ch = makeChart(0x1f8a8a, 0xff5a36, scene);
            chart = ch.group;
            bars = ch.bars;
            chart.position.set(2.5, 0, 1.15);
            solids.push(chart);
            titles = [
                { text: 'Next token', obj: phone, dy: 1.15 },
                { text: 'The scores', obj: chart, dy: 2.35 }
            ];
        } else if (LOOK === 'island') {
            scene.background = new T.Color(0x141824);
            scene.fog = new T.Fog(0x141824, 14, 32);
            scene.add(new T.HemisphereLight(0x6a7394, 0x2a241c, 0.4));
            var warm = new T.PointLight(0xf2c14e, 1.4, 12, 2);
            warm.position.set(0.4, 2.4, 0.2);
            scene.add(warm);
            var island = new T.Mesh(new T.CylinderGeometry(5.4, 6.0, 1.5, 6), mat(0x3c6b45, 0.9, 0, true));
            island.position.y = -0.2;
            island.receiveShadow = true;
            island.castShadow = true;
            scene.add(island);
            box(5.2, 0.16, 5.2, 0xc4a574, 0, 0.55, 0, scene, true);
            phone = makePhone(0xe07a5f, 0x243056, scene);
            phone.position.set(-2.2, 1.45, 0.4);
            chips = makeChips(0xf2cc8f, scene, true);
            chips.position.set(-3.6, 0.55, 2.35);
            var builtI = makeCar(0x4a6fa5, scene);
            car = builtI.group;
            wheels = builtI.wheels;
            car.position.set(-1.35, 0.55, 0.7);
            makeHouse(0xf4f1de, 0xc45c26, scene, true).position.set(2.15, 0.55, -1.7);
            makeCity(0x8d8478, scene, true).position.set(0.9, 0.55, -2.05);
            var chI = makeChart(0x81b29a, 0xe07a5f, scene, true);
            chart = chI.group;
            bars = chI.bars;
            chart.position.set(1.7, 0.55, 2.15);
            [-2.8, 2.6, -1.2].forEach(function (x, i) {
                var tree = new T.Mesh(new T.ConeGeometry(0.38, 0.95, 5), mat(0x2f6b3a, 0.9, 0, true));
                tree.position.set(x, 1.15, i === 1 ? -2.2 : 2.4);
                tree.castShadow = true;
                scene.add(tree);
            });
            titles = [
                { text: 'Next token', obj: phone, dy: 1.2 },
                { text: 'The scores', obj: chart, dy: 2.3 }
            ];
        } else if (LOOK === 'tabletop') {
            scene.background = new T.Color(0xe7e1d6);
            scene.add(new T.HemisphereLight(0xfff8ee, 0xb7aa96, 0.55));
            key.intensity = 0.9;
            var table = box(14, 0.2, 9, 0xf7f3ea, 0, -0.1, 0, scene);
            table.receiveShadow = true;
            phone = makePhone(0x2c3038, 0x1a1c22, scene);
            phone.rotation.x = -0.95;
            phone.position.set(-1.7, 0.55, 0.15);
            chips = makeChips(0xf4efe4, scene);
            chips.position.set(-1.9, 0, 1.35);
            var builtT = makeCar(0x8a9099, scene);
            car = builtT.group;
            wheels = builtT.wheels;
            car.scale.set(0.48, 0.48, 0.48);
            car.position.set(0.15, 0, -1.15);
            makeHouse(0xf7f4ee, 0xd97757, scene).position.set(-2.5, 0, -1.15);
            makeCity(0xc5c0b6, scene).position.set(2.15, 0, -1.25);
            var chT = makeChart(0x4c6cb3, 0xd97757, scene);
            chart = chT.group;
            bars = chT.bars;
            chart.rotation.x = -0.55;
            chart.position.set(1.55, 0.15, 0.85);
            titles = [
                { text: 'Next token', obj: phone, dy: 0.4 },
                { text: 'The scores', obj: chart, dy: 1.4 }
            ];
        } else {
            scene.background = new T.Color(0xe7dcc8);
            scene.add(new T.HemisphereLight(0xfff6ea, 0xb08968, 0.5));
            var sheet = paperMat('#f3e6d0');
            var left = add(new T.BoxGeometry(3.6, 0.08, 4.8), sheet, -1.9, 0.04, 0, scene);
            var right = add(new T.BoxGeometry(3.6, 0.08, 4.8), sheet, 1.9, 0.04, 0, scene);
            left.receiveShadow = true;
            right.receiveShadow = true;
            box(0.16, 0.12, 4.8, 0xc4b49a, 0, 0.05, 0, scene);
            function pop(mesh, x, z, delay, scale) {
                if (scale) mesh.scale.set(scale, scale, scale);
                var h = new T.Group();
                h.position.set(x, 0.08, z);
                h.add(mesh);
                var box3 = new T.Box3().setFromObject(mesh);
                mesh.position.y -= box3.min.y;
                scene.add(h);
                hinges.push({ h: h, delay: delay });
                return mesh;
            }
            phone = pop(makePhone(0xf4efe4, 0x2a4b8d, new T.Group()), -2.6, -0.6, 0.2, 0.72);
            chips = pop(makeChips(0xf6e7c1, new T.Group()), -2.4, 1.3, 1.4, 0.85);
            var builtP = makeCar(0xd97757, new T.Group());
            car = pop(builtP.group, -1.2, 0.5, 2.6, 0.42);
            wheels = builtP.wheels;
            pop(makeHouse(0xfffaf3, 0xc45c26, new T.Group()), 1.4, -1.15, 9.2, 0.7);
            pop(makeCity(0xe7d7c3, new T.Group()), 2.7, -0.9, 10.5, 0.55);
            var chP = makeChart(0x7d9a78, 0xd97757, new T.Group());
            chart = pop(chP.group, 1.9, 1.05, 9.8, 0.58);
            bars = chP.bars;
            titles = [
                { text: 'Next token', obj: phone, dy: 1.3 },
                { text: 'The scores', obj: chart, dy: 2.0 }
            ];
        }

        [phone, car, chips].forEach(function (m) {
            if (m && solids.indexOf(m) < 0) solids.push(m);
        });
        pack = { scene: scene, persp: persp, ortho: ortho, renderer: renderer, gl: gl };
    }

    function placeCamera(t) {
        var u = ease(t, 8.2, 10.4);
        var cam = LOOK === 'island' ? pack.ortho : pack.persp;
        if (LOOK === 'tilt') {
            var fx = -1.4 + u * 3.4;
            cam.position.set(fx + 0.2, 5.4, 7.4);
            cam.lookAt(fx, 0.15, 0.35);
        } else if (LOOK === 'island') {
            var ix = -0.6 + u * 1.8;
            cam.position.set(ix + 9.5, 10.5, 9.5);
            cam.lookAt(ix, 0.7, 0.1);
            cam.zoom = 1.05;
            cam.updateProjectionMatrix();
        } else if (LOOK === 'tabletop') {
            var ang = -0.35 + u * 0.85;
            cam.position.set(Math.sin(ang) * 6.2, 4.6, Math.cos(ang) * 5.4);
            cam.lookAt(-0.2 + u * 1.1, 0.35, 0.05);
        } else {
            cam.position.set(Math.sin(t * 0.12) * 0.7, 4.4, 6.6);
            cam.lookAt(u * 0.8, 0.7, 0);
        }
        return cam;
    }

    function animate(t) {
        var start = (film.ideas && film.ideas[1] && +film.ideas[1].t0) || 9;
        bars.forEach(function (b, i) {
            var u = ease(t, start + i * 0.28, start + 1.3 + i * 0.28);
            if (LOOK === 'popup') u = ease(t, 10.2 + i * 0.25, 12.2 + i * 0.25);
            b.scale.y = Math.max(0.04, u);
            b.position.y = (b.userData.full * b.scale.y) / 2 + 0.08;
        });
        var spin = t * 2.4;
        wheels.forEach(function (w) { w.rotation.x = spin; });
        if (car && LOOK !== 'popup') car.position.x += Math.sin(t * 0.7) * 0;
        if (car && LOOK === 'tilt') car.position.x = -0.8 + Math.sin(t * 0.45) * 0.7;
        if (LOOK === 'island') {
            var rise = ease(t, 0.3, 2.4);
            if (phone) phone.position.y = 0.55 + 0.84 * rise;
            if (chips) chips.position.y = 0.55 * rise;
            if (car) car.position.y = 0.55 * ease(t, 1.2, 3.2);
            if (chart) chart.position.y = 0.55 * ease(t, 8.4, 10.2);
        }
        hinges.forEach(function (item) {
            var u = ease(t, item.delay, item.delay + 1.3);
            item.h.rotation.x = -1.35 * (1 - u);
        });
    }

    var drawn = [];
    var blockers = [];
    function screenBox(obj) {
        var box = new T.Box3().setFromObject(obj);
        var cam = LOOK === 'island' ? pack.ortho : pack.persp;
        var xs = [], ys = [];
        [[0, 0, 0], [0, 0, 1], [0, 1, 0], [0, 1, 1], [1, 0, 0], [1, 0, 1], [1, 1, 0], [1, 1, 1]].forEach(function (c) {
            var p = new T.Vector3(
                box.min.x + (box.max.x - box.min.x) * c[0],
                box.min.y + (box.max.y - box.min.y) * c[1],
                box.min.z + (box.max.z - box.min.z) * c[2]
            );
            p.project(cam);
            if (p.z > 1) return;
            xs.push((p.x * 0.5 + 0.5) * 1920);
            ys.push((-p.y * 0.5 + 0.5) * 1080);
        });
        if (xs.length < 2) return null;
        var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
        var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
        return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    }
    function stamp(ctx, text, x, y, size, color) {
        var w = text.length * size * 0.58;
        var h = size * 1.15;
        x -= w / 2;
        var spots = [[0, 0], [0, -h], [-w, 0], [w, 0], [0, h], [-w, -h], [w, -h]];
        var placed = null;
        for (var s = 0; s < spots.length; s++) {
            var sx = x + spots[s][0], sy = y + spots[s][1];
            var hit = drawn.some(function (d) {
                return sx < d.x + d.w + 10 && sx + w + 10 > d.x && sy < d.y + d.h + 6 && sy + h + 6 > d.y;
            }) || blockers.some(function (d) {
                return d && sx < d.x + d.w && sx + w > d.x && sy < d.y + d.h && sy + h > d.y;
            });
            if (!hit) { placed = { x: sx, y: sy }; break; }
        }
        if (!placed) return;
        x = placed.x;
        y = placed.y;
        var mx = 1920 * 0.06, my = 1080 * 0.06;
        if (x < mx || y < my || x + w > 1920 - mx || y + h > 1080 - my) return;
        ctx.font = '700 ' + size + 'px Kalam, cursive';
        ctx.fillStyle = color;
        ctx.fillText(text, x, y);
        drawn.push({ x: x, y: y, w: w, h: h });
    }
    function front(obj, dist) {
        var v = new T.Vector3();
        obj.getWorldPosition(v);
        var cam = LOOK === 'island' ? pack.ortho : pack.persp;
        var toward = new T.Vector3(cam.position.x - v.x, 0, cam.position.z - v.z);
        if (toward.length() < 0.01) toward.set(0, 0, 1);
        toward.normalize();
        var best = null;
        [dist, dist * 0.4, 0.2].forEach(function (d) {
            if (best) return;
            var p = v.clone().add(toward.clone().multiplyScalar(d));
            p.y = 0.05;
            p.project(cam);
            var x = (p.x * 0.5 + 0.5) * 1920;
            var y = (-p.y * 0.5 + 0.5) * 1080;
            if (p.z < 1 && x > 80 && x < 1840 && y > 80 && y < 980) best = p;
        });
        return best;
    }
    function drawLabels(ctx) {
        drawn = [];
        blockers = [];
        solids.forEach(function (obj) {
            var b = screenBox(obj);
            if (b) blockers.push(b);
        });
        var cam = LOOK === 'island' ? pack.ortho : pack.persp;
        var ink = '#241c16';
        ctx.save();
        ctx.textBaseline = 'top';
        ctx.textAlign = 'left';
        function above(obj) {
            var box = new T.Box3().setFromObject(obj);
            var top = [
                new T.Vector3(box.min.x, box.max.y, box.min.z),
                new T.Vector3(box.max.x, box.max.y, box.min.z),
                new T.Vector3(box.min.x, box.max.y, box.max.z),
                new T.Vector3(box.max.x, box.max.y, box.max.z)
            ];
            var xs = [], ys = [];
            top.forEach(function (p) {
                p.project(cam);
                if (p.z > 1) return;
                xs.push((p.x * 0.5 + 0.5) * 1920);
                ys.push((-p.y * 0.5 + 0.5) * 1080);
            });
            if (!xs.length) return null;
            var x = xs.reduce(function (a, b) { return a + b; }, 0) / xs.length;
            var y = Math.min.apply(null, ys) - 46;
            return { x: x, y: y };
        }
        titles.forEach(function (lab) {
            if (!lab.obj) return;
            var at = above(lab.obj);
            if (!at) return;
            stamp(ctx, lab.text, at.x, at.y, 40, ink);
        });
        if (chips) chips.children.forEach(function (chip) {
            var v = front(chip, 0.55);
            if (v) stamp(ctx, chip.userData.label, (v.x * 0.5 + 0.5) * 1920, (-v.y * 0.5 + 0.5) * 1080, 26, ink);
        });
        var row = [];
        bars.forEach(function (b) {
            if (b.scale.y < 0.55) return;
            var v = front(b, 0.95);
            if (!v) return;
            row.push({ text: b.userData.label, x: (v.x * 0.5 + 0.5) * 1920, y: (-v.y * 0.5 + 0.5) * 1080 });
        });
        if (row.length) {
            var base = 0;
            row.forEach(function (item) { if (item.y > base) base = item.y; });
            row.forEach(function (item) {
                stamp(ctx, item.text, item.x, base + 4, 26, ink);
            });
        }
        ctx.restore();
    }

    function tiltBands(ctx, gl) {
        if (LOOK !== 'tilt') return;
        ctx.save();
        ctx.filter = 'blur(20px)';
        ctx.beginPath();
        ctx.rect(0, 0, 1920, 170);
        ctx.clip();
        ctx.drawImage(gl, 0, 0, 1920, 1080);
        ctx.restore();
        ctx.save();
        ctx.filter = 'blur(20px)';
        ctx.beginPath();
        ctx.rect(0, 900, 1920, 180);
        ctx.clip();
        ctx.drawImage(gl, 0, 0, 1920, 1080);
        ctx.restore();
    }

    function paint(ctx, canvas, t) {
        try {
            if (!pack) build();
            var k = window.devicePixelRatio || 1;
            if (canvas.width !== 1920 * k || canvas.height !== 1080 * k) {
                canvas.width = 1920 * k;
                canvas.height = 1080 * k;
                canvas.style.width = '1920px';
                canvas.style.height = '1080px';
            }
            ctx.setTransform(k, 0, 0, k, 0, 0);
            animate(t);
            var cam = placeCamera(t);
            pack.renderer.render(pack.scene, cam);
            var bg = LOOK === 'island' ? '#141824' : (LOOK === 'tilt' ? '#8fd0f2' : (LOOK === 'popup' ? '#e7dcc8' : '#e7e1d6'));
            ctx.fillStyle = bg;
            ctx.fillRect(0, 0, 1920, 1080);
            ctx.drawImage(pack.gl, 0, 0, 1920, 1080);
            tiltBands(ctx, pack.gl);
            drawLabels(ctx);
        } catch (err) {
            window.__err = String(err && err.stack || err);
            ctx.fillStyle = '#201c18';
            ctx.fillRect(0, 0, 1920, 1080);
        }
    }

    window.XVBoard.paint = paint;
})();
