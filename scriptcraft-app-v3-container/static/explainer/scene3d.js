/* Original 3D looks. Three.js r149 (MIT). Not copied from Lemo-Opuscar.
   Headings are drawn at 92px and body type at 52px in the 1920 canvas,
   which is 61px and 35px on a 1280x720 frame. */
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
    window.XVBoard.ink = '#e23b2e';

    var pack = null;
    var bars = [];
    var wheels = [];
    var car = null;
    var phone = null;
    var chart = null;
    var chips = null;
    var hinges = [];
    var drops = [];
    var hero = null;

    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function ease(t, a, b) {
        var u = clamp((t - a) / Math.max(0.001, b - a), 0, 1);
        return u * u * (3 - 2 * u);
    }
    function arrive(t, a, b) {
        var u = clamp((t - a) / Math.max(0.001, b - a), 0, 1);
        if (u <= 0) return 0;
        if (u >= 1) return 1;
        var s = u < 0.72 ? u / 0.72 : 1;
        s = s * s * (3 - 2 * s);
        if (u > 0.72) {
            var w = (u - 0.72) / 0.28;
            s = 1 + Math.sin(w * Math.PI) * 0.1 * (1 - w);
        }
        return s;
    }
    function lerp(a, b, u) { return a + (b - a) * u; }
    function srgb(hex) {
        var c = new T.Color(hex);
        if (c.convertSRGBToLinear) c.convertSRGBToLinear();
        return c;
    }
    function mat(color, rough, metal, flat) {
        return new T.MeshStandardMaterial({
            color: srgb(color), roughness: rough == null ? 0.46 : rough,
            metalness: metal || 0, flatShading: !!flat
        });
    }
    function markSRGB(tex) {
        if (T.sRGBEncoding) tex.encoding = T.sRGBEncoding;
        if (T.SRGBColorSpace && Object.prototype.hasOwnProperty.call(tex, 'colorSpace')) tex.colorSpace = T.SRGBColorSpace;
        tex.needsUpdate = true;
        return tex;
    }
    function texCanvas(w, h, draw) {
        var c = document.createElement('canvas');
        c.width = w; c.height = h;
        draw(c.getContext('2d'), w, h);
        return markSRGB(new T.CanvasTexture(c));
    }
    function woodTex() {
        return texCanvas(256, 256, function (g) {
            g.fillStyle = '#8a4a22';
            g.fillRect(0, 0, 256, 256);
            for (var y = 0; y < 256; y += 18) {
                g.fillStyle = (y / 18) % 2 ? '#c47a34' : '#5c3014';
                g.fillRect(0, y, 256, 16);
                g.strokeStyle = 'rgba(40,16,4,0.55)';
                g.beginPath();
                for (var x = 0; x < 260; x += 6) g.lineTo(x, y + 8 + Math.sin(x * 0.05 + y) * 3);
                g.stroke();
            }
        });
    }
    function paperTex(hex) {
        return texCanvas(128, 128, function (g) {
            g.fillStyle = hex;
            g.fillRect(0, 0, 128, 128);
            g.fillStyle = 'rgba(90,40,12,0.22)';
            for (var i = 0; i < 700; i++) g.fillRect((i * 19) % 128, (i * 47) % 128, 1, 2);
        });
    }
    function screenTex() {
        return texCanvas(256, 526, function (g) {
            g.fillStyle = '#14233f';
            g.fillRect(0, 0, 256, 526);
            g.fillStyle = '#2f6fed';
            g.fillRect(0, 0, 256, 78);
            g.fillStyle = '#f4f7fb';
            g.font = '700 32px sans-serif';
            g.fillText('Chat', 18, 50);
            g.fillStyle = '#d5e4f7';
            g.fillRect(18, 110, 200, 18);
            g.fillRect(18, 146, 160, 18);
            g.fillRect(18, 182, 180, 18);
            g.fillStyle = '#e07a5f';
            g.fillRect(22, 250, 48, 150);
            g.fillStyle = '#7eb8a2';
            g.fillRect(84, 300, 48, 100);
            g.fillStyle = '#f2cc8f';
            g.fillRect(146, 220, 48, 180);
            g.fillStyle = '#3a4e72';
            g.fillRect(18, 440, 220, 52);
            g.fillStyle = '#f4f7fb';
            g.font = '600 22px sans-serif';
            g.fillText('Send', 92, 474);
        });
    }
    function addMesh(geo, material, x, y, z, parent) {
        var m = new T.Mesh(geo, material);
        m.position.set(x, y, z);
        m.castShadow = true;
        m.receiveShadow = true;
        (parent || pack && pack.scene).add(m);
        return m;
    }
    function box(w, h, d, color, x, y, z, parent, flat) {
        return addMesh(new T.BoxGeometry(w, h, d), mat(color, flat ? 0.86 : 0.55, 0, flat), x, y, z, parent);
    }

    function makePhone(parent) {
        var g = new T.Group();
        box(0.82, 1.68, 0.11, 0x2a3038, 0, 0, 0, g);
        var screen = new T.Mesh(new T.BoxGeometry(0.68, 1.4, 0.02), new T.MeshStandardMaterial({
            color: srgb(0xffffff), map: screenTex(), emissive: srgb(0xffffff),
            emissiveMap: screenTex(), emissiveIntensity: 0.72, roughness: 0.32, metalness: 0.02
        }));
        screen.position.set(0, 0.02, 0.065);
        screen.castShadow = true;
        g.add(screen);
        box(0.26, 0.07, 0.025, 0x1a1e24, 0, 0.58, 0.08, g);
        parent.add(g);
        return g;
    }

    function makeSedan(color, parent) {
        var s = 0.0082;
        function P(x, y) { return [(x - 8) * s, (130 - y) * s]; }
        var outline = [[8, 96], [8, 64], [30, 52], [95, 52], [150, 16], [245, 16], [300, 50], [340, 54], [372, 64], [392, 80], [376, 96], [349, 96], [334, 70], [315, 62], [296, 70], [281, 96], [119, 96], [104, 70], [85, 62], [66, 70], [51, 96]];
        var shape = new T.Shape();
        var p0 = P(outline[0][0], outline[0][1]);
        shape.moveTo(p0[0], p0[1]);
        for (var i = 1; i < outline.length; i++) {
            var p = P(outline[i][0], outline[i][1]);
            shape.lineTo(p[0], p[1]);
        }
        shape.closePath();
        var bodyGeo = new T.ExtrudeGeometry(shape, {
            depth: 1.12, bevelEnabled: true, bevelThickness: 0.018, bevelSize: 0.02, bevelSegments: 1
        });
        bodyGeo.translate(0, 0, -0.56);
        var body = new T.Mesh(bodyGeo, mat(color, 0.45, 0.08));
        body.castShadow = true;
        body.receiveShadow = true;
        var g = new T.Group();
        g.add(body);
        var glassPts = [[100, 52], [155, 21], [240, 21], [290, 52]];
        var glass = new T.Shape();
        var gp = P(glassPts[0][0], glassPts[0][1]);
        glass.moveTo(gp[0], gp[1]);
        for (var j = 1; j < glassPts.length; j++) {
            var q = P(glassPts[j][0], glassPts[j][1]);
            glass.lineTo(q[0], q[1]);
        }
        glass.closePath();
        var gGeo = new T.ExtrudeGeometry(glass, { depth: 0.04, bevelEnabled: false });
        var glassMat = new T.MeshStandardMaterial({
            color: srgb(0x7ec8ea), roughness: 0.08, metalness: 0.15, transparent: true, opacity: 0.88
        });
        [-0.60, 0.56].forEach(function (z) {
            var band = new T.Mesh(gGeo, glassMat);
            band.position.z = z;
            g.add(band);
        });
        box(0.12, 0.08, 0.9, 0xffe7a8, P(374, 70)[0], P(374, 70)[1], 0, g);
        box(0.1, 0.07, 0.7, 0xe45a5a, P(22, 64)[0], P(22, 64)[1], 0, g);
        var local = [];
        [[85, 96], [315, 96]].forEach(function (wp) {
            [-1, 1].forEach(function (side) {
                var wheel = new T.Mesh(new T.CylinderGeometry(34 * s, 34 * s, 0.18, 20), mat(0x1a1f28, 0.7, 0.05));
                wheel.geometry.rotateX(Math.PI / 2);
                var at = P(wp[0], wp[1]);
                wheel.position.set(at[0], at[1], side * 0.64);
                wheel.castShadow = true;
                g.add(wheel);
                local.push(wheel);
                var hub = new T.Mesh(new T.CylinderGeometry(18 * s, 18 * s, 0.19, 12), mat(0xd5dde6, 0.35, 0.4));
                hub.geometry.rotateX(Math.PI / 2);
                hub.position.copy(wheel.position);
                g.add(hub);
            });
        });
        parent.add(g);
        g.userData.len = (392 - 8) * s;
        return { group: g, wheels: local };
    }

    function makeHouse(wall, roof, parent, flat) {
        var g = new T.Group();
        box(1.35, 1.05, 1.15, wall, 0, 0.52, 0, g, flat);
        var top = new T.Mesh(new T.ConeGeometry(1.05, 0.62, 4), mat(roof, 0.75, 0, flat));
        top.position.y = 1.22;
        top.rotation.y = Math.PI / 4;
        top.castShadow = true;
        g.add(top);
        box(0.28, 0.46, 0.04, 0xf2cc8f, 0, 0.38, 0.58, g, flat);
        [[-0.38, 0.72], [0.38, 0.72]].forEach(function (w) {
            var win = box(0.22, 0.22, 0.04, 0xffe1a8, w[0], w[1], 0.58, g, flat);
            win.material = win.material.clone();
            win.material.emissive = srgb(0xffb703);
            win.material.emissiveIntensity = 0.85;
        });
        parent.add(g);
        return g;
    }
    function makeTree(parent, x, z, flat) {
        var g = new T.Group();
        box(0.12, 0.45, 0.12, 0x6b4630, 0, 0.22, 0, g, flat);
        var leaf = new T.Mesh(new T.ConeGeometry(0.38, 0.85, flat ? 5 : 8), mat(0x168a32, 0.72, 0, flat));
        leaf.position.y = 0.78;
        leaf.castShadow = true;
        g.add(leaf);
        g.position.set(x, 0, z);
        parent.add(g);
        return g;
    }
    function makePerson(parent, x, z, shirt) {
        var g = new T.Group();
        box(0.22, 0.36, 0.14, shirt, 0, 0.34, 0, g);
        var head = new T.Mesh(new T.SphereGeometry(0.11, 10, 8), mat(0xf0c9a0, 0.55, 0));
        head.position.y = 0.62;
        head.castShadow = true;
        g.add(head);
        box(0.07, 0.26, 0.07, 0x243044, -0.06, 0.13, 0, g);
        box(0.07, 0.26, 0.07, 0x243044, 0.06, 0.13, 0, g);
        g.position.set(x, 0, z);
        parent.add(g);
        return g;
    }
    function makeCity(parent, flat, a, b) {
        var g = new T.Group();
        var colors = [a || 0xf4efe6, b || 0x8d8a9a];
        [0.8, 1.35, 1.05, 1.7, 0.95].forEach(function (h, i) {
            var bld = box(0.42, h, 0.42, i % 2 ? colors[0] : colors[1], i * 0.52, h / 2, 0, g, flat);
            bld.material = bld.material.clone();
            bld.material.emissive = srgb(0xffb703);
            bld.material.emissiveIntensity = LOOK === 'island' ? 0.45 : 0.1;
        });
        parent.add(g);
        return g;
    }
    function makeChart(barColor, win, parent, flat) {
        var g = new T.Group();
        box(3.2, 0.08, 1.05, 0xfff6ea, 0, 0.04, 0, g, flat);
        var heights = [0.85, 1.35, 0.62, 2.05];
        var names = ['a', 'the', 'on', 'mat'];
        var made = heights.map(function (h, i) {
            var b = box(0.46, h, 0.46, i === 3 ? win : barColor, -1.05 + i * 0.72, h / 2 + 0.08, 0, g, flat);
            b.userData.full = h;
            b.userData.label = names[i];
            b.scale.y = 0.04;
            b.position.y = 0.12;
            return b;
        });
        parent.add(g);
        return { group: g, bars: made };
    }
    function makeChips(parent, flat, color) {
        var g = new T.Group();
        ['The', 'cat', 'sat', 'on'].forEach(function (word, i) {
            var chip = box(0.78, 0.42, 0.28, color || 0xffd15c, i * 0.92, 0.21, 0, g, flat);
            chip.userData.label = word;
        });
        parent.add(g);
        return g;
    }

    function trackDrop(obj, restY, delay, dur, lift) {
        obj.userData.restY = restY;
        obj.userData.lift = lift || 1.6;
        obj.position.y = restY + obj.userData.lift;
        drops.push({ obj: obj, delay: delay, dur: dur || 0.95 });
    }

    function build() {
        var scene = new T.Scene();
        var persp = new T.PerspectiveCamera(30, 1920 / 1080, 0.08, 80);
        var ortho = new T.OrthographicCamera(-7.2, 7.2, 4.05, -4.05, 0.1, 80);
        var renderer = new T.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
        renderer.setSize(1920, 1080, false);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = T.PCFSoftShadowMap;
        // r149 reads outputEncoding. SRGBColorSpace exists, outputColorSpace does not.
        if (T.sRGBEncoding) renderer.outputEncoding = T.sRGBEncoding;
        if (T.ACESFilmicToneMapping != null) {
            renderer.toneMapping = T.ACESFilmicToneMapping;
            renderer.toneMappingExposure = 1.1;
        }
        var key = new T.DirectionalLight(0xfff1dc, 2.7);
        key.position.set(-6, 12, 7);
        key.castShadow = true;
        key.shadow.mapSize.set(2048, 2048);
        key.shadow.camera.near = 0.4;
        key.shadow.camera.far = 36;
        key.shadow.camera.left = -12;
        key.shadow.camera.right = 12;
        key.shadow.camera.top = 12;
        key.shadow.camera.bottom = -12;
        key.shadow.bias = -0.0008;
        if ('normalBias' in key.shadow) key.shadow.normalBias = 0.02;
        scene.add(key);
        var hemiSky = LOOK === 'island' ? 0x8eb4ff : (LOOK === 'popup' ? 0xffd7a8 : 0xb7e6ff);
        scene.add(new T.HemisphereLight(hemiSky, 0x1a120c, 0.2));
        scene.add(new T.AmbientLight(0xffffff, 0.045));
        function groundShadow(x, y, z, rx, rz) {
            var geo = new T.CircleGeometry(1, 24);
            geo.rotateX(-Math.PI / 2);
            var m = new T.Mesh(geo, new T.MeshBasicMaterial({
                color: 0x000000, transparent: true, opacity: 0.4, depthWrite: false
            }));
            m.position.set(x, y, z);
            m.scale.set(rx, 1, rz);
            m.renderOrder = 2;
            scene.add(m);
        }

        if (LOOK === 'tilt') {
            scene.background = new T.Color(0x1aa7e6);
            var ground = box(20, 0.3, 14, 0x18b84a, 0, -0.15, 0, scene);
            ground.receiveShadow = true;
            box(18, 0.05, 1.7, 0x3d4452, 0, 0.03, 0.9, scene);
            for (var dash = -6; dash <= 6; dash += 1.1) box(0.55, 0.02, 0.08, 0xfff6ea, dash, 0.07, 0.9, scene);
            phone = makePhone(scene);
            phone.position.set(-2.4, 0.84, -0.55);
            trackDrop(phone, 0.84, 0.15);
            groundShadow(-2.4, 0.035, -0.55, 0.55, 0.38);
            chips = makeChips(scene);
            chips.position.set(-3.5, 0, 1.55);
            chips.children.forEach(function (chip, i) { trackDrop(chip, 0.21, 0.8 + i * 0.28); });
            var built = makeSedan(0x1d6bff, scene);
            car = built.group;
            wheels = built.wheels;
            car.position.set(-2.6, 0, 0.85);
            trackDrop(car, 0, 1.1);
            groundShadow(-1.8, 0.035, 0.85, 1.15, 0.55);
            var house = makeHouse(0xfff3d0, 0xff3b30, scene);
            house.position.set(1.6, 0, -2.15);
            trackDrop(house, 0, 0.4);
            makeHouse(0xfff3d0, 0x1f9d55, scene).position.set(-4.2, 0, -2.0);
            makeCity(scene, false, 0xfff6ea, 0x6d7a90).position.set(4.0, 0, -2.3);
            [-3.2, -0.4, 3.2].forEach(function (x, i) { makeTree(scene, x, -2.6 + (i % 2) * 0.3); });
            [[-1.2, 1.7, 0xff3b30], [2.4, 1.8, 0x1f9d55], [3.6, 2.0, 0xffc107], [-4.6, 1.5, 0x2456d6]].forEach(function (p) {
                makePerson(scene, p[0], p[1], p[2]);
            });
            var ch = makeChart(0x14d2c8, 0xff4d1a, scene);
            chart = ch.group;
            bars = ch.bars;
            chart.position.set(3.1, 0, 0.15);
            hero = phone;
        } else if (LOOK === 'island') {
            scene.background = new T.Color(0x0c1428);
            var water = new T.Mesh(new T.CylinderGeometry(9.2, 9.2, 0.25, 28), mat(0x0b7f86, 0.28, 0.08));
            water.position.y = -0.55;
            water.receiveShadow = true;
            scene.add(water);
            [[0.2, -1.8, 0.85, 1.35], [-2.4, -1.2, 0.6, 1.05], [2.1, -1.4, 0.7, 1.2], [1.6, 1.6, 0.5, 0.85], [-2.2, 1.4, 0.45, 0.8], [-3.6, -2.3, 0.4, 0.55], [3.6, -2.0, 0.48, 0.62], [0.15, -2.9, 0.36, 0.48]].forEach(function (h) {
                var hex = new T.Mesh(new T.CylinderGeometry(h[2], h[2] + 0.18, h[3], 6), mat(h[3] > 1.05 ? 0x2f9e44 : 0x1b7a3a, 0.82, 0, true));
                hex.position.set(h[0], h[3] / 2 - 0.85, h[1]);
                hex.castShadow = true;
                hex.receiveShadow = true;
                scene.add(hex);
            });
            var pad = box(4.6, 0.12, 3.6, 0xe0a84a, 0.1, 0.42, 0.15, scene, true);
            pad.receiveShadow = true;
            phone = makePhone(scene);
            phone.position.set(-1.55, 1.35, 0.15);
            chips = makeChips(scene, true, 0xf0c14a);
            groundShadow(-1.55, 0.5, 0.15, 0.5, 0.36);
            chips.position.set(-2.85, 0.48, -1.15);
            var builtI = makeSedan(0x3d8bfd, scene);
            car = builtI.group;
            wheels = builtI.wheels;
            car.position.set(0.85, 0.48, -0.35);
            car.scale.set(0.5, 0.5, 0.5);
            makeHouse(0xfff3d0, 0xe25b2a, scene, true).position.set(2.15, 0.48, 0.85);
            var cityI = makeCity(scene, true, 0xffe8b0, 0xd08a45);
            cityI.scale.set(0.62, 0.62, 0.62);
            cityI.position.set(0.7, 0.48, -1.45);
            makeTree(scene, -2.6, -0.2, true);
            makeTree(scene, 2.4, -1.5, true);
            var warm = new T.PointLight(0xffb703, 2.4, 12, 2);
            warm.position.set(0.2, 2.2, 0.2);
            scene.add(warm);
            var chI = makeChart(0x2fbf71, 0xff5a36, scene, true);
            chart = chI.group;
            bars = chI.bars;
            chart.position.set(0.05, 0.48, 1.55);
            hero = phone;
        } else if (LOOK === 'tabletop') {
            scene.background = new T.Color(0x6e5344);
            var table = new T.Mesh(new T.BoxGeometry(16, 0.28, 10), new T.MeshStandardMaterial({
                map: woodTex(), roughness: 0.62, metalness: 0.02, color: srgb(0xffffff)
            }));
            table.position.y = -0.14;
            table.receiveShadow = true;
            scene.add(table);
            phone = makePhone(scene);
            phone.position.set(-1.15, 0.84, 0.1);
            trackDrop(phone, 0.84, 0.2, 2.7);
            groundShadow(-1.15, 0.04, 0.1, 0.5, 0.36);
            chips = makeChips(scene, false, 0xffd56a);
            chips.position.set(-3.35, 0, 1.5);
            chips.children.forEach(function (chip, i) { trackDrop(chip, 0.21, 2.55 + i * 0.32, 1.35); });
            var builtT = makeSedan(0x2f6fe0, scene);
            car = builtT.group;
            wheels = builtT.wheels;
            car.scale.set(0.42, 0.42, 0.42);
            car.position.set(0.4, 0, -1.35);
            trackDrop(car, 0, 3.15, 1.55);
            makeHouse(0xfff8ee, 0xe25b2a, scene).position.set(-2.6, 0, -1.2);
            makeCity(scene, false, 0xfff3d6, 0xc47a3a).position.set(2.6, 0, -1.45);
            var chT = makeChart(0x2f6fe0, 0xff5a36, scene);
            chart = chT.group;
            bars = chT.bars;
            chart.position.set(1.7, 0, 0.35);
            trackDrop(chart, 0, 7.5, 2.6, 7);
            hero = phone;
        } else {
            scene.background = new T.Color(0xc47a3a);
            var sheet = new T.MeshStandardMaterial({ map: paperTex('#fff6e4'), roughness: 0.84, metalness: 0, color: srgb(0xffffff) });
            var left = addMesh(new T.BoxGeometry(3.7, 0.07, 5.0), sheet, -1.95, 0.04, 0, scene);
            var right = addMesh(new T.BoxGeometry(3.7, 0.07, 5.0), sheet, 1.95, 0.04, 0, scene);
            left.receiveShadow = true;
            right.receiveShadow = true;
            box(0.1, 0.06, 5.05, 0x3e2a1c, 0, 0.08, 0, scene);
            [[-3.78, 0], [3.78, 0]].forEach(function (edge) {
                box(0.07, 0.1, 4.55, 0xe4d7c4, edge[0], 0.02, 0, scene);
            });
            [[-3.62, -1], [3.62, 1]].forEach(function (edge) {
                var curl = new T.Mesh(new T.CylinderGeometry(0.12, 0.12, 1.4, 12, 1, false, 0, Math.PI), sheet);
                curl.rotation.z = Math.PI / 2;
                curl.rotation.y = edge[1] > 0 ? 0.75 : -0.75;
                curl.position.set(edge[0], 0.16, 0);
                curl.castShadow = true;
                scene.add(curl);
            });
            function pop(mesh, x, z, delay, scale, dur) {
                if (scale) mesh.scale.set(scale, scale, scale);
                var h = new T.Group();
                h.position.set(x, 0.08, z);
                h.add(mesh);
                var box3 = new T.Box3().setFromObject(mesh);
                mesh.position.y -= box3.min.y;
                scene.add(h);
                hinges.push({ h: h, delay: delay, dur: dur || 1.15 });
                return mesh;
            }
            phone = pop(makePhone(new T.Group()), -2.05, -0.15, 0.2, 0.92, 6.8);
            chips = pop(makeChips(new T.Group(), false, 0xffd15c), -2.35, 1.45, 2.15, 0.72, 2.3);
            var builtP = makeSedan(0xe23b2e, new T.Group());
            car = pop(builtP.group, -0.45, 0.15, 2.5, 0.4, 2.2);
            wheels = builtP.wheels;
            pop(makeHouse(0xfff6e8, 0xf0a202, new T.Group()), 1.15, -1.25, 6.9, 0.62, 3.4);
            pop(makeCity(new T.Group(), false, 0xffe08a, 0xf08a24), 2.7, -0.7, 8.2, 0.46, 2.8);
            var chP = makeChart(0x1f9d6a, 0xe23b2e, new T.Group());
            chart = pop(chP.group, 1.7, 1.05, 7.5, 0.58, 3.6);
            bars = chP.bars;
            hero = phone;
        }

        pack = { scene: scene, persp: persp, ortho: ortho, renderer: renderer, gl: renderer.domElement };
    }

    function focusAt(t) {
        var travel = ease(t, 5.2, 7.6);
        var reveal = ease(t, 16.2, 18.4);
        var spin = 0;
        if (travel < 0.08) spin = ease(t, 0.8, 5.0) * 0.9;
        else if (travel > 0.92 && reveal < 0.08) spin = ease(t, 8.4, 15.2) * 0.62;
        return { travel: travel, reveal: reveal, spin: spin };
    }
    function swing(eye, at, ang) {
        var dx = eye.x - at.x, dz = eye.z - at.z;
        var c = Math.cos(ang), s = Math.sin(ang);
        return { x: at.x + dx * c - dz * s, y: eye.y, z: at.z + dx * s + dz * c };
    }

    function placeCamera(t) {
        var f = focusAt(t);
        var u = f.travel;
        var r = f.reveal;
        var cam = LOOK === 'island' ? pack.ortho : pack.persp;
        function mix(a, b, c, k) {
            var p = { x: lerp(lerp(a.x, b.x, u), c.x, k), y: lerp(lerp(a.y, b.y, u), c.y, k), z: lerp(lerp(a.z, b.z, u), c.z, k) };
            return p;
        }
        var eye, at, zoom;
        if (LOOK === 'tilt') {
            eye = mix({ x: -2.2, y: 1.7, z: 5.15 }, { x: 3.15, y: 2.5, z: 6.5 }, { x: 0.3, y: 3.8, z: 6.4 }, r);
            at = mix({ x: -2.3, y: 0.75, z: -0.3 }, { x: 3.15, y: 0.85, z: 0.05 }, { x: 0.5, y: 0.4, z: 0.1 }, r);
        } else if (LOOK === 'island') {
            eye = mix({ x: 3.4, y: 5.6, z: 4.8 }, { x: 5.6, y: 5.4, z: 6.2 }, { x: 6.6, y: 7.6, z: 6.6 }, r);
            at = mix({ x: -1.45, y: 1.0, z: 0.15 }, { x: 0.35, y: 0.85, z: 1.15 }, { x: 0.2, y: 1.05, z: 0.15 }, r);
            zoom = lerp(lerp(2.0, 1.62, u), 1.72, r);
        } else if (LOOK === 'tabletop') {
            eye = mix({ x: -1.05, y: 1.35, z: 4.35 }, { x: 2.05, y: 2.55, z: 7.3 }, { x: 0.35, y: 2.7, z: 7.2 }, r);
            at = mix({ x: -1.1, y: 0.72, z: 0.05 }, { x: 1.65, y: 0.65, z: 0.2 }, { x: 0.45, y: 0.5, z: 0.05 }, r);
        } else {
            eye = mix({ x: -1.7, y: 1.7, z: 3.7 }, { x: 1.7, y: 2.15, z: 4.7 }, { x: 0.1, y: 3.9, z: 6.9 }, r);
            at = mix({ x: -1.85, y: 0.7, z: -0.05 }, { x: 1.65, y: 0.55, z: 0.55 }, { x: 0.0, y: 0.25, z: 0.0 }, r);
        }
        eye = swing(eye, at, f.spin);
        cam.position.set(eye.x, eye.y, eye.z);
        cam.lookAt(at.x, at.y, at.z);
        if (zoom && cam.isOrthographicCamera) {
            cam.zoom = zoom;
            cam.updateProjectionMatrix();
        }
        pack.aim = at;
        pack.aimCam = cam;
        return cam;
    }

    function animate(t) {
        bars.forEach(function (b, i) {
            var a0 = 9.0 + i * 0.28;
            var a1 = 14.2 + i * 0.2;
            if (LOOK === 'popup') { a0 = 12.0 + i * 0.22; a1 = 15.6 + i * 0.12; }
            var u = arrive(t, a0, a1);
            b.scale.y = Math.max(0.04, u);
            b.position.y = (b.userData.full * b.scale.y) / 2 + 0.08;
        });
        var spin = t * 2.6;
        wheels.forEach(function (w) { w.rotation.z = spin; });
            if (car && LOOK === 'tilt') car.position.x = -3.1 + ease(t, 3.2, 13) * 1.7;
        drops.forEach(function (item) {
            var u = arrive(t, item.delay, item.delay + (item.dur || 0.95));
            item.obj.visible = u > 0.001;
            var rest = item.obj.userData.restY;
            if (rest == null) rest = item.obj.position.y;
            item.obj.position.y = rest + (1 - u) * (item.obj.userData.lift || 1.6);
        });
        if (LOOK === 'island') {
            var rp = arrive(t, 0.25, 4.3);
            if (phone) phone.position.y = 0.48 + 0.84 * rp + (1 - rp) * 1.45;
            var rc = arrive(t, 7.7, 11.4);
            if (chart) chart.position.y = 0.48 + (rc - 1) * 1.7;
            if (car) {
                var ru = arrive(t, 1.8, 4.5);
                car.position.y = 0.48 * ru + (1 - ru) * 1.5;
            }
            chips.children.forEach(function (chip, i) {
                var cu = arrive(t, 1.1 + i * 0.35, 4.0 + i * 0.2);
                chip.position.y = 0.21 * cu + (1 - cu) * 1.2;
            });
        }
        hinges.forEach(function (item) {
            var u = arrive(t, item.delay, item.delay + (item.dur || 1.15));
            item.h.rotation.x = -1.25 * (1 - u);
        });
    }

    function heroSpan(obj, cam) {
        if (!obj) return 0;
        var box = new T.Box3().setFromObject(obj);
        if (!isFinite(box.min.x)) return 0;
        var xs = [], ys = [];
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]].forEach(function (c) {
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
        if (xs.length < 2) return 0;
        var w = (Math.max.apply(null, xs) - Math.min.apply(null, xs)) / 1920;
        var h = (Math.max.apply(null, ys) - Math.min.apply(null, ys)) / 1080;
        return Math.max(w, h);
    }

    function drawType(ctx, t) {
        var f = focusAt(t);
        var ink = (LOOK === 'island' || LOOK === 'tabletop') ? '#fff6e8' : '#1a120c';
        var head = 92;
        var body = 52;
        ctx.save();
        ctx.textBaseline = 'top';
        ctx.textAlign = 'left';
        ctx.fillStyle = ink;
        ctx.shadowColor = (LOOK === 'island' || LOOK === 'tabletop') ? 'rgba(0,0,0,0.65)' : 'rgba(255,255,255,0.72)';
        ctx.shadowBlur = 6;
        var mx = 1920 * 0.06;
        var my = 1080 * 0.06;
        function title(text, x, y, size) {
            ctx.font = '700 ' + size + 'px Kalam, cursive';
            if (x < mx) x = mx;
            if (y < my) y = my;
            ctx.fillText(text, x, y);
        }
        if (f.reveal > 0.55) {
            title('Next token', mx, my, head);
            title('The scores', 1160, my, head);
        } else if (f.travel < 0.45) {
            title('Next token', mx, my, head);
            title('Reads the prompt', mx, my + 108, body);
            ['The', 'cat', 'sat', 'on'].forEach(function (word, i) {
                title(word, mx, my + 186 + i * 58, body);
            });
        } else {
            title('The scores', mx, my, head);
            title('Taller bar wins', mx, my + 108, body);
        }
        if (f.travel >= 0.45 || f.reveal > 0.5) labelUnderBars(ctx, pack.aimCam);
        ctx.restore();
    }

    function labelUnderBars(ctx, cam) {
        if (!cam) return;
        var size = 48;
        var mx = 1920 * 0.06, my = 1080 * 0.06;
        var right = 1920 - mx, bottom = 1080 - my;
        ctx.font = '700 ' + size + 'px Kalam, cursive';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        var placed = [];
        bars.forEach(function (b) {
            var center = new T.Vector3();
            b.getWorldPosition(center);
            if (center.y < 0.05) return;
            var half = (b.userData.full * Math.abs(b.scale.y)) / 2;
            var foot = b.localToWorld(new T.Vector3(0, -half, 0.24));
            var p = foot.clone().project(cam);
            if (p.z > 1) return;
            var text = b.userData.label || '';
            var w = Math.ceil(ctx.measureText(text).width);
            var x = (p.x * 0.5 + 0.5) * 1920;
            var y = (-p.y * 0.5 + 0.5) * 1080 + 28;
            if (LOOK === 'tilt' && y > 752) y = 752;
            if (x - w / 2 < mx) x = mx + w / 2;
            if (x + w / 2 > right) x = right - w / 2;
            if (y < my) y = my;
            if (y + size > bottom) y = bottom - size;
            var box = { x: x - w / 2, y: y, w: w, h: size };
            for (var i = 0; i < placed.length; i++) {
                var o = placed[i];
                var overlap = box.x < o.x + o.w + 6 && box.x + box.w + 6 > o.x && box.y < o.y + o.h + 4 && box.y + box.h + 4 > o.y;
                if (overlap && LOOK !== 'tilt' && box.y + size + 4 <= bottom) {
                    box.y = o.y + o.h + 6;
                    y = box.y;
                }
            }
            if (box.x < mx - 1 || box.x + box.w > right + 1 || box.y + box.h > bottom + 1) return;
            placed.push(box);
            ctx.lineWidth = 7;
            ctx.strokeStyle = 'rgba(255,255,255,0.94)';
            ctx.strokeText(text, x, y);
            ctx.fillStyle = '#1a120c';
            ctx.fillText(text, x, y);
        });
    }

    function blurBands(ctx, gl, strong) {
        var bands = strong
            ? [[0, 150, 22], [790, 290, 34]]
            : [[0, 80, 10], [960, 120, 14]];
        bands.forEach(function (b) {
            ctx.save();
            ctx.filter = 'blur(' + b[2] + 'px)';
            ctx.beginPath();
            ctx.rect(0, b[0], 1920, b[1]);
            ctx.clip();
            ctx.drawImage(gl, 0, 0, 1920, 1080);
            ctx.restore();
        });
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
            var focus = focusAt(t);
            var subject = focus.travel < 0.5 ? phone : chart;
            if (focus.reveal > 0.5) {
                subject = phone;
                [phone, chart, car].forEach(function (o) {
                    if (o && heroSpan(o, cam) > heroSpan(subject, cam)) subject = o;
                });
            }
            pack.renderer.render(pack.scene, cam);
            var bg = LOOK === 'island' ? '#0c1428' : (LOOK === 'tilt' ? '#1aa7e6' : (LOOK === 'popup' ? '#c47a3a' : '#6e5344'));
            ctx.fillStyle = bg;
            ctx.fillRect(0, 0, 1920, 1080);
            ctx.drawImage(pack.gl, 0, 0, 1920, 1080);
            if (LOOK === 'tilt') blurBands(ctx, pack.gl, true);
            if (LOOK === 'tabletop') blurBands(ctx, pack.gl, false);
            drawType(ctx, t);
            hero = subject;
            window.__review = {
                head: 92, body: 52,
                hero: Math.round(heroSpan(subject, cam) * 100) / 100,
                t: t, look: LOOK
            };
            window.__err = '';
        } catch (err) {
            window.__err = String(err && err.stack || err);
            ctx.fillStyle = '#201818';
            ctx.fillRect(0, 0, 1920, 1080);
        }
    }

    window.XVBoard.paint = paint;
})();
