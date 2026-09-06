// ==========================================================================
// SMART EXPENSE TRACKER - 3D THREE.JS WEBGL ENGINES, ANIMATIONS & THEME
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    initMobileNav();
    init3DTilt();
    initAnimatedCounters();
    initClipboard();
    initGlobal3DBackground();
});

/**
 * 1. Dark & Bright Mode Theme Switcher
 */
function initThemeToggle() {
    const savedTheme = localStorage.getItem('smart_tracker_theme') || 'dark';
    if (typeof window.applyTheme === 'function') {
        window.applyTheme(savedTheme);
    } else {
        document.documentElement.setAttribute('data-theme', savedTheme);
        document.documentElement.setAttribute('data-bs-theme', savedTheme);
        if (document.body) {
            document.body.setAttribute('data-theme', savedTheme);
            document.body.setAttribute('data-bs-theme', savedTheme);
        }
    }
}

/**
 * 2. Mobile Responsive Navigation Collapse Toggler
 */
function initMobileNav() {
    const toggler = document.getElementById('navbar-toggler-btn');
    const menu = document.getElementById('navMenuCollapse');
    if (!toggler || !menu) return;

    toggler.addEventListener('click', () => {
        menu.classList.toggle('show');
    });

    // Close menu when clicking outside
    document.addEventListener('click', (e) => {
        if (!toggler.contains(e.target) && !menu.contains(e.target)) {
            menu.classList.remove('show');
        }
    });
}

/**
 * 3. Animated Stat Numbers Count-up
 */
function initAnimatedCounters() {
    const statElements = document.querySelectorAll('.stat-val');
    statElements.forEach(el => {
        const text = el.innerText.trim();
        // Check for currency format: ₹1,234.56 or 1234.56
        const match = text.match(/₹?\s*([\d,]+(?:\.\d+)?)/);
        if (!match) return;

        const rawNum = parseFloat(match[1].replace(/,/g, ''));
        if (isNaN(rawNum) || rawNum === 0) return;

        const hasRupee = text.includes('₹');
        const hasDecimals = match[1].includes('.');
        const duration = 1000; // ms
        const startTime = performance.now();

        function updateNumber(currentTime) {
            const progress = Math.min((currentTime - startTime) / duration, 1);
            // Ease out cubic
            const easeProgress = 1 - Math.pow(1 - progress, 3);
            const currentVal = rawNum * easeProgress;

            const formatted = currentVal.toLocaleString('en-IN', {
                minimumFractionDigits: hasDecimals ? 2 : 0,
                maximumFractionDigits: hasDecimals ? 2 : 0
            });

            el.innerText = (hasRupee ? '₹' : '') + formatted;

            if (progress < 1) {
                requestAnimationFrame(updateNumber);
            } else {
                el.innerText = text; // Ensure exact final text
            }
        }
        requestAnimationFrame(updateNumber);
    });
}

/**
 * 4. 3D Tilt & Interactive Specular Glare on Cards
 */
function init3DTilt() {
    const cards = document.querySelectorAll('.card-3d');

    cards.forEach(card => {
        // Create specular glare overlay if not already present
        if (!card.querySelector('.card-glare')) {
            const glare = document.createElement('div');
            glare.className = 'card-glare';
            card.appendChild(glare);
        }

        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            const centerX = rect.width / 2;
            const centerY = rect.height / 2;

            // Maximum tilt angle (+/- 8 deg)
            const rotateX = ((y - centerY) / centerY) * -8;
            const rotateY = ((x - centerX) / centerX) * 8;

            card.style.transform = `perspective(1000px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateZ(10px)`;

            // Update glare position
            card.style.setProperty('--glare-x', `${x}px`);
            card.style.setProperty('--glare-y', `${y}px`);
        });

        card.addEventListener('mouseleave', () => {
            card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) translateZ(0px)';
        });
    });
}

/**
 * 5. Global 3D Ambient Space Background Engine (Three.js)
 */
function initGlobal3DBackground() {
    const canvas = document.getElementById('bg-3d-canvas');
    if (!canvas || typeof THREE === 'undefined') return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 30;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Theme responsive lighting
    let isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';

    const ambientLight = new THREE.AmbientLight(isDark ? 0xa855f7 : 0x93c5fd, isDark ? 1.0 : 1.2);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(isDark ? 0x00f0ff : 0x38bdf8, isDark ? 1.8 : 1.2);
    dirLight1.position.set(25, 25, 20);
    scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(isDark ? 0xff007f : 0xa855f7, isDark ? 1.4 : 0.6);
    dirLight2.position.set(-25, -20, 15);
    scene.add(dirLight2);

    // Glowing 3D Geometric tokens
    const geometries = [
        new THREE.IcosahedronGeometry(1.3, 0),
        new THREE.OctahedronGeometry(1.1, 0),
        new THREE.TetrahedronGeometry(1.2, 0),
        new THREE.TorusGeometry(1.1, 0.28, 14, 28)
    ];

    const darkNeonColors = [0x00f0ff, 0xa855f7, 0xff007f, 0x00ff9d];
    const lightColors = [0x4f46e5, 0x0284c7, 0x7c3aed, 0x059669];

    const items = [];
    const count = window.innerWidth < 768 ? 18 : 32;

    for (let i = 0; i < count; i++) {
        const geo = geometries[i % geometries.length];
        const colorPalette = isDark ? darkNeonColors : lightColors;
        const color = colorPalette[i % colorPalette.length];

        const mat = new THREE.MeshStandardMaterial({
            color: color,
            emissive: isDark ? color : 0x000000,
            emissiveIntensity: isDark ? 0.45 : 0.05,
            wireframe: i % 3 === 0,
            roughness: isDark ? 0.15 : 0.25,
            metalness: isDark ? 0.85 : 0.5,
            transparent: true,
            opacity: isDark ? 0.65 : 0.3
        });

        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(
            (Math.random() - 0.5) * 65,
            (Math.random() - 0.5) * 50,
            (Math.random() - 0.5) * 40
        );

        mesh.rotation.set(
            Math.random() * Math.PI,
            Math.random() * Math.PI,
            Math.random() * Math.PI
        );

        mesh.userData = {
            rotSpeedX: (Math.random() - 0.5) * 0.012,
            rotSpeedY: (Math.random() - 0.5) * 0.012,
            floatSpeed: 0.001 + Math.random() * 0.0025,
            initialY: mesh.position.y
        };

        scene.add(mesh);
        items.push(mesh);
    }

    // Glowing Neon Stardust Particle System
    const particleCount = window.innerWidth < 768 ? 160 : 320;
    const particleGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const particleColors = new Float32Array(particleCount * 3);

    const neonPalette = [
        new THREE.Color(0x00f0ff),
        new THREE.Color(0xa855f7),
        new THREE.Color(0xff007f),
        new THREE.Color(0x00ff9d)
    ];

    for (let p = 0; p < particleCount; p++) {
        positions[p * 3] = (Math.random() - 0.5) * 80;
        positions[p * 3 + 1] = (Math.random() - 0.5) * 60;
        positions[p * 3 + 2] = (Math.random() - 0.5) * 50;

        const c = neonPalette[p % neonPalette.length];
        particleColors[p * 3] = c.r;
        particleColors[p * 3 + 1] = c.g;
        particleColors[p * 3 + 2] = c.b;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    particleGeo.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));

    const particleMat = new THREE.PointsMaterial({
        size: 1.4,
        vertexColors: true,
        transparent: true,
        opacity: isDark ? 0.75 : 0.3,
        blending: THREE.AdditiveBlending
    });

    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    // React to theme changes
    window.addEventListener('themeChanged', (e) => {
        const isNowDark = e.detail.theme === 'dark';
        ambientLight.color.setHex(isNowDark ? 0xa855f7 : 0x93c5fd);
        ambientLight.intensity = isNowDark ? 1.0 : 1.2;
        dirLight1.color.setHex(isNowDark ? 0x00f0ff : 0x38bdf8);
        dirLight2.color.setHex(isNowDark ? 0xff007f : 0xa855f7);

        const palette = isNowDark ? darkNeonColors : lightColors;
        items.forEach((item, idx) => {
            const col = palette[idx % palette.length];
            item.material.color.setHex(col);
            item.material.emissive.setHex(isNowDark ? col : 0x000000);
            item.material.emissiveIntensity = isNowDark ? 0.45 : 0.05;
            item.material.opacity = isNowDark ? 0.65 : 0.3;
            item.material.needsUpdate = true;
        });

        particleMat.opacity = isNowDark ? 0.75 : 0.3;
    });

    // Mouse parallax tracking
    let mouseX = 0;
    let mouseY = 0;
    window.addEventListener('mousemove', (e) => {
        mouseX = (e.clientX / window.innerWidth - 0.5) * 4;
        mouseY = (e.clientY / window.innerHeight - 0.5) * 4;
    });

    // Responsive window resize
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    let clock = new THREE.Clock();
    function animate() {
        requestAnimationFrame(animate);
        const elapsedTime = clock.getElapsedTime();

        items.forEach((item, index) => {
            item.rotation.x += item.userData.rotSpeedX;
            item.rotation.y += item.userData.rotSpeedY;
            item.position.y = item.userData.initialY + Math.sin(elapsedTime * 1.5 + index) * 1.6;
        });

        particles.rotation.y += 0.0006;
        particles.rotation.x += 0.0003;

        // Smooth camera parallax
        camera.position.x += (mouseX - camera.position.x) * 0.03;
        camera.position.y += (-mouseY - camera.position.y) * 0.03;
        camera.lookAt(0, 0, 0);

        renderer.render(scene, camera);
    }
    animate();
}

/**
 * 6. Dashboard Interactive 3D Glowing Financial Core (Three.js)
 */
function initDashboard3DCore(canvasId, isOver, percentSpent) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    function getContainerSize() {
        const parent = canvas.parentElement;
        const w = parent.clientWidth || 300;
        const h = parent.clientHeight || 260;
        return { w, h };
    }

    let { w, h } = getContainerSize();

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
    camera.position.z = 7;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Dynamic glowing neon color depending on budget status
    let coreColor = 0x00f0ff; // Neon Cyan
    if (isOver) {
        coreColor = 0xff007f; // Hot Neon Magenta
    } else if (percentSpent >= 80) {
        coreColor = 0xffb703; // Neon Amber
    }

    // Glowing Core 3D Polyhedron with high emissive intensity
    const coreGeo = new THREE.IcosahedronGeometry(1.6, 1);
    const coreMat = new THREE.MeshStandardMaterial({
        color: coreColor,
        emissive: coreColor,
        emissiveIntensity: 0.65,
        roughness: 0.1,
        metalness: 0.95,
        wireframe: false,
    });
    const core = new THREE.Mesh(coreGeo, coreMat);
    scene.add(core);

    // Glowing Wireframe exoskeleton for cyber look
    const wireMat = new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, transparent: true, opacity: 0.45 });
    const wireMesh = new THREE.Mesh(coreGeo, wireMat);
    core.add(wireMesh);

    // Glowing Orbital Ring 1 (Electric Purple)
    const ring1Geo = new THREE.TorusGeometry(2.4, 0.05, 16, 64);
    const ring1Mat = new THREE.MeshStandardMaterial({
        color: 0xa855f7,
        emissive: 0xa855f7,
        emissiveIntensity: 0.85,
        roughness: 0.2,
        metalness: 0.85
    });
    const ring1 = new THREE.Mesh(ring1Geo, ring1Mat);
    ring1.rotation.x = Math.PI / 3;
    scene.add(ring1);

    // Glowing Orbital Ring 2 (Neon Cyan)
    const ring2Geo = new THREE.TorusGeometry(2.9, 0.04, 16, 64);
    const ring2Mat = new THREE.MeshStandardMaterial({
        color: 0x00f0ff,
        emissive: 0x00f0ff,
        emissiveIntensity: 0.85,
        roughness: 0.2,
        metalness: 0.85
    });
    const ring2 = new THREE.Mesh(ring2Geo, ring2Mat);
    ring2.rotation.y = Math.PI / 4;
    scene.add(ring2);

    // Intense dynamic PointLights from core
    const pointLight = new THREE.PointLight(coreColor, 3.5, 25);
    pointLight.position.set(2, 2, 4);
    scene.add(pointLight);

    const pointLight2 = new THREE.PointLight(0xa855f7, 2.2, 20);
    pointLight2.position.set(-3, -2, 3);
    scene.add(pointLight2);

    const ambient = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambient);

    // Mouse & Touch Drag 3D Rotation
    let isDragging = false;
    let prevPos = { x: 0, y: 0 };

    function onPointerDown(clientX, clientY) {
        isDragging = true;
        prevPos = { x: clientX, y: clientY };
    }

    function onPointerMove(clientX, clientY) {
        if (!isDragging) return;
        const deltaX = clientX - prevPos.x;
        const deltaY = clientY - prevPos.y;

        core.rotation.y += deltaX * 0.01;
        core.rotation.x += deltaY * 0.01;
        ring1.rotation.z += deltaX * 0.005;

        prevPos = { x: clientX, y: clientY };
    }

    function onPointerUp() {
        isDragging = false;
    }

    canvas.addEventListener('mousedown', (e) => onPointerDown(e.clientX, e.clientY));
    window.addEventListener('mouseup', onPointerUp);
    window.addEventListener('mousemove', (e) => onPointerMove(e.clientX, e.clientY));

    canvas.addEventListener('touchstart', (e) => {
        if (e.touches.length > 0) onPointerDown(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: true });
    window.addEventListener('touchend', onPointerUp);
    window.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) onPointerMove(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: true });

    function animate() {
        requestAnimationFrame(animate);
        if (!isDragging) {
            core.rotation.y += 0.008;
            core.rotation.x += 0.004;
            ring1.rotation.z += 0.012;
            ring2.rotation.x += 0.009;
        }
        renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
        const size = getContainerSize();
        camera.aspect = size.w / size.h;
        camera.updateProjectionMatrix();
        renderer.setSize(size.w, size.h);
    });
}

/**
 * 7. Add Expense Page 3D Currency Coin (Three.js)
 */
function initExpenseCoin3D(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    const width = canvas.parentElement.clientWidth || 240;
    const height = 220;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 50);
    camera.position.z = 5.5;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Metallic 3D Cylinder Coin with glowing neon edge
    const coinGeo = new THREE.CylinderGeometry(1.6, 1.6, 0.22, 48);
    const coinMat = new THREE.MeshStandardMaterial({
        color: 0xffb703,
        emissive: 0xffb703,
        emissiveIntensity: 0.25,
        metalness: 0.95,
        roughness: 0.15,
    });
    const coin = new THREE.Mesh(coinGeo, coinMat);
    coin.rotation.x = Math.PI / 2.2;
    scene.add(coin);

    // Glowing Neon Edge Ridges
    const edgeGeo = new THREE.TorusGeometry(1.6, 0.06, 16, 48);
    const edgeMat = new THREE.MeshStandardMaterial({
        color: 0x00f0ff,
        emissive: 0x00f0ff,
        emissiveIntensity: 0.75,
        metalness: 0.9,
        roughness: 0.1
    });
    const edge = new THREE.Mesh(edgeGeo, edgeMat);
    coin.add(edge);

    // Directional Light
    const light = new THREE.DirectionalLight(0x00f0ff, 2.0);
    light.position.set(5, 5, 5);
    scene.add(light);

    const ambient = new THREE.AmbientLight(0xffb703, 0.7);
    scene.add(ambient);

    let spinSpeed = 0.018;

    // Listen to amount input to accelerate coin spin!
    const amountInput = document.querySelector('input[name="amount"]');
    if (amountInput) {
        amountInput.addEventListener('input', () => {
            spinSpeed = 0.09;
            setTimeout(() => { spinSpeed = 0.018; }, 900);
        });
    }

    function animate() {
        requestAnimationFrame(animate);
        coin.rotation.z += spinSpeed;
        coin.rotation.y = Math.sin(Date.now() * 0.002) * 0.3;
        renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
        const w = canvas.parentElement.clientWidth || 240;
        camera.aspect = w / height;
        camera.updateProjectionMatrix();
        renderer.setSize(w, height);
    });
}

/**
 * 8. Profile Page 3D Connection Beacon (Three.js)
 */
function initProfile3DBeacon(canvasId, isLinked) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    const width = canvas.parentElement.clientWidth || 240;
    const height = 200;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 50);
    camera.position.z = 5;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    const color = isLinked ? 0x00ff9d : 0x00f0ff;

    // 3D Diamond / Octahedron Beacon with glowing neon emission
    const beaconGeo = new THREE.OctahedronGeometry(1.3, 0);
    const beaconMat = new THREE.MeshStandardMaterial({
        color: color,
        emissive: color,
        emissiveIntensity: 0.65,
        metalness: 0.9,
        roughness: 0.15,
        wireframe: false
    });
    const beacon = new THREE.Mesh(beaconGeo, beaconMat);
    scene.add(beacon);

    // Glowing Orbiting neon ring
    const ringGeo = new THREE.TorusGeometry(1.9, 0.05, 16, 64);
    const ringMat = new THREE.MeshStandardMaterial({
        color: 0xa855f7,
        emissive: 0xa855f7,
        emissiveIntensity: 0.8,
        wireframe: true
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = Math.PI / 2.5;
    scene.add(ring);

    // Lights
    const pLight = new THREE.PointLight(color, 3.0, 15);
    pLight.position.set(2, 3, 4);
    scene.add(pLight);
    scene.add(new THREE.AmbientLight(0xffffff, 0.5));

    function animate() {
        requestAnimationFrame(animate);
        beacon.rotation.y += 0.014;
        beacon.rotation.z += 0.007;
        ring.rotation.z -= 0.018;
        renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
        const w = canvas.parentElement.clientWidth || 240;
        camera.aspect = w / height;
        camera.updateProjectionMatrix();
        renderer.setSize(w, height);
    });
}

/**
 * 9. Auth Pages (Login & Register) 3D Cyber Vault Prism
 */
function initAuth3DCube(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    const width = 120;
    const height = 120;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 50);
    camera.position.z = 4;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    const boxGeo = new THREE.BoxGeometry(1.4, 1.4, 1.4);
    const boxMat = new THREE.MeshStandardMaterial({
        color: 0xa855f7,
        emissive: 0xa855f7,
        emissiveIntensity: 0.55,
        metalness: 0.85,
        roughness: 0.15,
        wireframe: false
    });
    const box = new THREE.Mesh(boxGeo, boxMat);
    scene.add(box);

    const wireGeo = new THREE.BoxGeometry(1.48, 1.48, 1.48);
    const wireMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff, wireframe: true, transparent: true, opacity: 0.8 });
    const wire = new THREE.Mesh(wireGeo, wireMat);
    box.add(wire);

    const light = new THREE.PointLight(0x00f0ff, 2.5, 12);
    light.position.set(3, 3, 3);
    scene.add(light);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));

    function animate() {
        requestAnimationFrame(animate);
        box.rotation.x += 0.012;
        box.rotation.y += 0.016;
        renderer.render(scene, camera);
    }
    animate();
}

/**
 * 10. Copy Telegram Link Code to clipboard
 */
function initClipboard() {
    const copyBtn = document.getElementById('copy-code-btn');
    if (!copyBtn) return;

    copyBtn.addEventListener('click', () => {
        const codeElement = document.getElementById('telegram-link-code');
        if (!codeElement) return;

        const codeText = codeElement.innerText.trim();
        navigator.clipboard.writeText(codeText).then(() => {
            const originalHtml = copyBtn.innerHTML;
            copyBtn.innerHTML = '✓ Copied!';
            copyBtn.classList.remove('btn-secondary-3d');
            copyBtn.classList.add('btn-cyan-3d');

            setTimeout(() => {
                copyBtn.innerHTML = originalHtml;
                copyBtn.classList.remove('btn-cyan-3d');
                copyBtn.classList.add('btn-secondary-3d');
            }, 2500);
        }).catch(err => {
            console.error('Failed to copy: ', err);
        });
    });
}
