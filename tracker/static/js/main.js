// ==========================================================================
// SMART EXPENSE TRACKER - REALISTIC 3D THREE.JS ENGINES & PREMIUM FINTECH UI
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    initMobileNav();
    init3DTilt();
    initAnimatedCounters();
    initClipboard();
    initGlobal3DBackground();
    initChartSwitcher();
});

/**
 * 1. Dark & Light Mode Theme Switcher
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
 * 2. Mobile Navigation Collapse Toggler
 */
function initMobileNav() {
    const toggler = document.getElementById('navbar-toggler-btn');
    const menu = document.getElementById('navMenuCollapse');
    if (!toggler || !menu) return;

    toggler.addEventListener('click', () => {
        menu.classList.toggle('show');
    });

    document.addEventListener('click', (e) => {
        if (!toggler.contains(e.target) && !menu.contains(e.target)) {
            menu.classList.remove('show');
        }
    });
}

/**
 * 3. Animated Stat Numbers with easeOutExpo Physics
 */
function initAnimatedCounters() {
    const statElements = document.querySelectorAll('.stat-val');
    statElements.forEach(el => {
        const text = el.innerText.trim();
        const match = text.match(/₹?\s*([\d,]+(?:\.\d+)?)/);
        if (!match) return;

        const rawNum = parseFloat(match[1].replace(/,/g, ''));
        if (isNaN(rawNum) || rawNum === 0) return;

        const hasRupee = text.includes('₹');
        const hasDecimals = match[1].includes('.');
        const duration = 1200; // ms
        const startTime = performance.now();

        function updateNumber(currentTime) {
            const progress = Math.min((currentTime - startTime) / duration, 1);
            // High-precision easeOutExpo: starts crisp, lands feather-soft
            const easeProgress = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
            const currentVal = rawNum * easeProgress;

            const formatted = currentVal.toLocaleString('en-IN', {
                minimumFractionDigits: hasDecimals ? 2 : 0,
                maximumFractionDigits: hasDecimals ? 2 : 0
            });

            el.innerText = (hasRupee ? '₹' : '') + formatted;

            if (progress < 1) {
                requestAnimationFrame(updateNumber);
            } else {
                el.innerText = text;
            }
        }
        requestAnimationFrame(updateNumber);
    });
}

/**
 * 4. Realistic 3D Tilt & Micro-Reflective Glare on Cards
 */
function init3DTilt() {
    const cards = document.querySelectorAll('.card-3d');

    cards.forEach(card => {
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

            // Restrained, premium tilt angle (+/- 5 deg)
            const rotateX = ((y - centerY) / centerY) * -5;
            const rotateY = ((x - centerX) / centerX) * 5;

            card.style.transform = `perspective(1200px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateY(-2px)`;

            card.style.setProperty('--glare-x', `${x}px`);
            card.style.setProperty('--glare-y', `${y}px`);
        });

        card.addEventListener('mouseleave', () => {
            card.style.transform = 'perspective(1200px) rotateX(0deg) rotateY(0deg) translateY(0px)';
        });
    });
}

/**
 * 5. Helper: Create Soft Bokeh Stardust Particle Texture
 */
function createParticleTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');

    const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, 'rgba(255, 255, 255, 1)');
    grad.addColorStop(0.25, 'rgba(220, 235, 255, 0.7)');
    grad.addColorStop(0.6, 'rgba(120, 160, 255, 0.2)');
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)');

    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 64, 64);

    const texture = new THREE.CanvasTexture(canvas);
    return texture;
}

/**
 * 6. Global Ambient 3D Stardust & Floating Metallic Crystals
 */
function initGlobal3DBackground() {
    const canvas = document.getElementById('bg-3d-canvas');
    if (!canvas || typeof THREE === 'undefined') return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 32;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    let isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';

    // Studio Lighting
    const ambientLight = new THREE.AmbientLight(isDark ? 0x1e293b : 0xe2e8f0, isDark ? 1.6 : 2.0);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(isDark ? 0x60a5fa : 0x3b82f6, isDark ? 1.8 : 1.2);
    keyLight.position.set(30, 30, 25);
    scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(isDark ? 0xc084fc : 0x8b5cf6, isDark ? 1.2 : 0.8);
    fillLight.position.set(-30, -25, 20);
    scene.add(fillLight);

    // Elegant Floating Metallic Facets
    const geometries = [
        new THREE.OctahedronGeometry(1.2, 0),
        new THREE.DodecahedronGeometry(1.1, 0),
        new THREE.IcosahedronGeometry(1.0, 0),
        new THREE.TorusGeometry(1.2, 0.15, 16, 36)
    ];

    // Refined luxury palette: Titanium slate, Platinum sapphire, Champagne gold, Emerald teal
    const darkPalette = [0x94a3b8, 0x38bdf8, 0x818cf8, 0xe2b93b, 0x34d399];
    const lightPalette = [0x64748b, 0x0284c7, 0x6366f1, 0xd97706, 0x059669];

    const items = [];
    const count = window.innerWidth < 768 ? 16 : 26;

    for (let i = 0; i < count; i++) {
        const geo = geometries[i % geometries.length];
        const palette = isDark ? darkPalette : lightPalette;
        const color = palette[i % palette.length];

        const mat = new THREE.MeshStandardMaterial({
            color: color,
            roughness: 0.25,
            metalness: 0.85,
            transparent: true,
            opacity: isDark ? 0.35 : 0.22,
            wireframe: i % 4 === 0
        });

        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(
            (Math.random() - 0.5) * 60,
            (Math.random() - 0.5) * 45,
            (Math.random() - 0.5) * 35
        );

        mesh.rotation.set(
            Math.random() * Math.PI * 2,
            Math.random() * Math.PI * 2,
            Math.random() * Math.PI * 2
        );

        mesh.userData = {
            rotSpeedX: (Math.random() - 0.5) * 0.008,
            rotSpeedY: (Math.random() - 0.5) * 0.008,
            floatSpeed: 0.0008 + Math.random() * 0.0018,
            initialY: mesh.position.y
        };

        scene.add(mesh);
        items.push(mesh);
    }

    // Soft Ambient Stardust Points
    const particleCount = window.innerWidth < 768 ? 140 : 260;
    const particleGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const particleColors = new Float32Array(particleCount * 3);

    const stardustColors = [
        new THREE.Color(0x93c5fd),
        new THREE.Color(0xc4b5fd),
        new THREE.Color(0xfde68a),
        new THREE.Color(0xa7f3d0)
    ];

    for (let p = 0; p < particleCount; p++) {
        positions[p * 3] = (Math.random() - 0.5) * 75;
        positions[p * 3 + 1] = (Math.random() - 0.5) * 55;
        positions[p * 3 + 2] = (Math.random() - 0.5) * 40;

        const c = stardustColors[p % stardustColors.length];
        particleColors[p * 3] = c.r;
        particleColors[p * 3 + 1] = c.g;
        particleColors[p * 3 + 2] = c.b;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    particleGeo.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));

    const particleTexture = createParticleTexture();
    const particleMat = new THREE.PointsMaterial({
        size: 1.8,
        map: particleTexture,
        vertexColors: true,
        transparent: true,
        opacity: isDark ? 0.65 : 0.35,
        blending: THREE.AdditiveBlending,
        depthWrite: false
    });

    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    // Dynamic Theme Listener
    window.addEventListener('themeChanged', (e) => {
        const isNowDark = e.detail.theme === 'dark';
        ambientLight.color.setHex(isNowDark ? 0x1e293b : 0xe2e8f0);
        ambientLight.intensity = isNowDark ? 1.6 : 2.0;
        keyLight.color.setHex(isNowDark ? 0x60a5fa : 0x3b82f6);
        fillLight.color.setHex(isNowDark ? 0xc084fc : 0x8b5cf6);

        const palette = isNowDark ? darkPalette : lightPalette;
        items.forEach((item, idx) => {
            const col = palette[idx % palette.length];
            item.material.color.setHex(col);
            item.material.opacity = isNowDark ? 0.35 : 0.22;
            item.material.needsUpdate = true;
        });

        particleMat.opacity = isNowDark ? 0.65 : 0.35;
    });

    // Mouse Parallax Tracking
    let mouseX = 0;
    let mouseY = 0;
    window.addEventListener('mousemove', (e) => {
        mouseX = (e.clientX / window.innerWidth - 0.5) * 3;
        mouseY = (e.clientY / window.innerHeight - 0.5) * 3;
    });

    // Responsive Resize
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    const clock = new THREE.Clock();
    function animate() {
        requestAnimationFrame(animate);
        const elapsedTime = clock.getElapsedTime();

        items.forEach((item, index) => {
            item.rotation.x += item.userData.rotSpeedX;
            item.rotation.y += item.userData.rotSpeedY;
            item.position.y = item.userData.initialY + Math.sin(elapsedTime * 1.2 + index) * 1.2;
        });

        particles.rotation.y += 0.0004;
        particles.rotation.x += 0.0002;

        camera.position.x += (mouseX - camera.position.x) * 0.03;
        camera.position.y += (-mouseY - camera.position.y) * 0.03;
        camera.lookAt(0, 0, 0);

        renderer.render(scene, camera);
    }
    animate();
}

/**
 * 7. Dashboard Interactive 3D Wealth Gyroscope Core
 */
function initDashboard3DCore(canvasId, isOver, percentSpent) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    function getContainerSize() {
        const parent = canvas.parentElement;
        const w = parent.clientWidth || 320;
        const h = parent.clientHeight || 270;
        return { w, h };
    }

    let { w, h } = getContainerSize();

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
    camera.position.z = 7.2;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Dynamic color reflecting financial health
    let coreColor = 0x3b82f6; // Royal Sapphire Blue
    let emissiveColor = 0x1d4ed8;
    if (isOver) {
        coreColor = 0xf43f5e; // Refined Crimson
        emissiveColor = 0xbe123c;
    } else if (percentSpent >= 80) {
        coreColor = 0xf59e0b; // Warm Bullion Gold
        emissiveColor = 0xb45309;
    }

    // Multifaceted Gemstone Core
    const coreGeo = new THREE.IcosahedronGeometry(1.45, 0);
    const coreMat = new THREE.MeshStandardMaterial({
        color: coreColor,
        emissive: emissiveColor,
        emissiveIntensity: 0.35,
        roughness: 0.18,
        metalness: 0.88,
        flatShading: true
    });
    const core = new THREE.Mesh(coreGeo, coreMat);
    scene.add(core);

    // Inner Radiant Star
    const innerGeo = new THREE.OctahedronGeometry(0.8, 0);
    const innerMat = new THREE.MeshStandardMaterial({
        color: 0xffffff,
        emissive: coreColor,
        emissiveIntensity: 0.8,
        roughness: 0.1,
        metalness: 0.95
    });
    const innerStar = new THREE.Mesh(innerGeo, innerMat);
    core.add(innerStar);

    // Precision Brushed Titanium Gimbal Ring 1
    const ring1Geo = new THREE.TorusGeometry(2.25, 0.05, 16, 64);
    const ring1Mat = new THREE.MeshStandardMaterial({
        color: 0x94a3b8,
        roughness: 0.2,
        metalness: 0.92
    });
    const ring1 = new THREE.Mesh(ring1Geo, ring1Mat);
    ring1.rotation.x = Math.PI / 3;
    scene.add(ring1);

    // Precision Champagne / Sapphire Gimbal Ring 2
    const ring2Geo = new THREE.TorusGeometry(2.7, 0.04, 16, 64);
    const ring2Mat = new THREE.MeshStandardMaterial({
        color: coreColor,
        emissive: emissiveColor,
        emissiveIntensity: 0.25,
        roughness: 0.25,
        metalness: 0.88
    });
    const ring2 = new THREE.Mesh(ring2Geo, ring2Mat);
    ring2.rotation.y = Math.PI / 4;
    scene.add(ring2);

    // Studio 3-Point Lighting
    const keyLight = new THREE.DirectionalLight(0xfff8ee, 2.2);
    keyLight.position.set(4, 5, 5);
    scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xa5b4fc, 1.4);
    fillLight.position.set(-4, -3, 3);
    scene.add(fillLight);

    const centerLight = new THREE.PointLight(coreColor, 2.0, 10);
    centerLight.position.set(0, 0, 0);
    scene.add(centerLight);

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    // Tactile Drag Physics with Damping & Momentum
    let isDragging = false;
    let prevPos = { x: 0, y: 0 };
    let velocity = { x: 0.008, y: 0.005 };

    function onPointerDown(clientX, clientY) {
        isDragging = true;
        prevPos = { x: clientX, y: clientY };
        velocity = { x: 0, y: 0 };
    }

    function onPointerMove(clientX, clientY) {
        if (!isDragging) return;
        const deltaX = clientX - prevPos.x;
        const deltaY = clientY - prevPos.y;

        core.rotation.y += deltaX * 0.012;
        core.rotation.x += deltaY * 0.012;
        ring1.rotation.z += deltaX * 0.006;
        ring2.rotation.x -= deltaY * 0.006;

        velocity = { x: deltaX * 0.005, y: deltaY * 0.005 };
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
            // Apply inertial damping decay down to resting ambient speed
            velocity.x = velocity.x * 0.95 + 0.006 * 0.05;
            velocity.y = velocity.y * 0.95 + 0.003 * 0.05;

            core.rotation.y += velocity.x;
            core.rotation.x += velocity.y;
            ring1.rotation.z += velocity.x * 1.2;
            ring2.rotation.x += velocity.y * 1.1;
        }

        innerStar.rotation.x -= 0.01;
        innerStar.rotation.y -= 0.015;

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
 * 8. Procedural Minted Bullion Coin Face Texture with ₹ Symbol
 */
function createCoinFaceTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 512;
    const ctx = canvas.getContext('2d');

    // Rich gold base with radial shimmer
    const grad = ctx.createRadialGradient(256, 256, 40, 256, 256, 250);
    grad.addColorStop(0, '#fef08a');
    grad.addColorStop(0.4, '#eab308');
    grad.addColorStop(0.85, '#ca8a04');
    grad.addColorStop(1, '#854d0e');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 512, 512);

    // Minted outer concentric ridges
    ctx.strokeStyle = '#fef08a';
    ctx.lineWidth = 14;
    ctx.beginPath();
    ctx.arc(256, 256, 240, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = '#713f12';
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.arc(256, 256, 226, 0, Math.PI * 2);
    ctx.stroke();

    // Inner beaded rim (traditional minted coin dots)
    const dotCount = 48;
    for (let i = 0; i < dotCount; i++) {
        const angle = (i / dotCount) * Math.PI * 2;
        const x = 256 + Math.cos(angle) * 210;
        const y = 256 + Math.sin(angle) * 210;
        ctx.fillStyle = '#fef9c3';
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
    }

    // Inner embossed circle
    ctx.strokeStyle = '#a16207';
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.arc(256, 256, 185, 0, Math.PI * 2);
    ctx.stroke();

    // Embossed Indian Rupee Symbol ₹
    ctx.font = 'bold 220px "Outfit", "Inter", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Emboss shadow
    ctx.fillStyle = '#713f12';
    ctx.fillText('₹', 259, 267);

    // Emboss highlight
    ctx.fillStyle = '#fef9c3';
    ctx.fillText('₹', 253, 261);

    // Main symbol
    ctx.fillStyle = '#ca8a04';
    ctx.fillText('₹', 256, 264);

    const texture = new THREE.CanvasTexture(canvas);
    texture.generateMipmaps = true;
    return texture;
}

/**
 * 9. Add Expense Page: Realistic Minted 3D Gold Bullion Coin
 */
function initExpenseCoin3D(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    const width = canvas.parentElement.clientWidth || 250;
    const height = 220;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 50);
    camera.position.z = 5.6;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    const coinFaceTexture = createCoinFaceTexture();

    // Cylinder with minted face textures on top & bottom caps
    const coinGeo = new THREE.CylinderGeometry(1.6, 1.6, 0.22, 64);

    // Material array: [0: edge, 1: top face, 2: bottom face]
    const edgeMat = new THREE.MeshStandardMaterial({
        color: 0xd97706,
        roughness: 0.35,
        metalness: 0.9
    });

    const faceMat = new THREE.MeshStandardMaterial({
        map: coinFaceTexture,
        roughness: 0.22,
        metalness: 0.88
    });

    const coinMaterials = [edgeMat, faceMat, faceMat];
    const coin = new THREE.Mesh(coinGeo, coinMaterials);
    coin.rotation.x = Math.PI / 2.3;
    scene.add(coin);

    // Polished Bullion Outer Bevel Rings for extra physical realism
    const rim1Geo = new THREE.TorusGeometry(1.6, 0.035, 16, 64);
    const rimMat = new THREE.MeshStandardMaterial({
        color: 0xfde047,
        roughness: 0.15,
        metalness: 0.95
    });
    const rim1 = new THREE.Mesh(rim1Geo, rimMat);
    rim1.position.y = 0.11;
    rim1.rotation.x = Math.PI / 2;
    coin.add(rim1);

    const rim2 = new THREE.Mesh(rim1Geo, rimMat);
    rim2.position.y = -0.11;
    rim2.rotation.x = Math.PI / 2;
    coin.add(rim2);

    // Studio 3-Point Lighting for Metallic Specular Glints
    const mainLight = new THREE.DirectionalLight(0xfffaed, 2.5);
    mainLight.position.set(5, 6, 6);
    scene.add(mainLight);

    const rimLight = new THREE.DirectionalLight(0x93c5fd, 1.6);
    rimLight.position.set(-5, -4, 4);
    scene.add(rimLight);

    const ambientLight = new THREE.AmbientLight(0xfffbeb, 0.8);
    scene.add(ambientLight);

    let baseSpinSpeed = 0.012;
    let currentSpinSpeed = 0.012;

    // React with realistic spin acceleration when user enters amounts
    const amountInput = document.querySelector('input[name="amount"]');
    if (amountInput) {
        amountInput.addEventListener('input', () => {
            currentSpinSpeed = 0.07;
        });
    }

    const clock = new THREE.Clock();
    function animate() {
        requestAnimationFrame(animate);
        const elapsedTime = clock.getElapsedTime();

        // Spin decay back to resting speed
        currentSpinSpeed = currentSpinSpeed * 0.96 + baseSpinSpeed * 0.04;

        coin.rotation.z += currentSpinSpeed;
        // Subtle organic precession wobble
        coin.rotation.y = Math.sin(elapsedTime * 1.8) * 0.22;
        coin.rotation.x = Math.PI / 2.3 + Math.cos(elapsedTime * 1.4) * 0.08;

        renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
        const w = canvas.parentElement.clientWidth || 250;
        camera.aspect = w / height;
        camera.updateProjectionMatrix();
        renderer.setSize(w, height);
    });
}

/**
 * 10. Profile Page: Quantum Satellite Connection Beacon
 */
function initProfile3DBeacon(canvasId, isLinked) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    const width = canvas.parentElement.clientWidth || 240;
    const height = 180;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 50);
    camera.position.z = 5.2;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    const statusColor = isLinked ? 0x10b981 : 0x3b82f6; // Emerald or Sapphire

    // Polished Satellite Core
    const sphereGeo = new THREE.SphereGeometry(1.0, 32, 32);
    const sphereMat = new THREE.MeshStandardMaterial({
        color: statusColor,
        roughness: 0.2,
        metalness: 0.85,
        emissive: statusColor,
        emissiveIntensity: 0.25
    });
    const sphere = new THREE.Mesh(sphereGeo, sphereMat);
    scene.add(sphere);

    // Precision Orbital Rings
    const ring1Geo = new THREE.TorusGeometry(1.7, 0.035, 16, 64);
    const ring1Mat = new THREE.MeshStandardMaterial({
        color: 0x94a3b8,
        roughness: 0.2,
        metalness: 0.95
    });
    const ring1 = new THREE.Mesh(ring1Geo, ring1Mat);
    ring1.rotation.x = Math.PI / 2.4;
    scene.add(ring1);

    const ring2Geo = new THREE.TorusGeometry(2.1, 0.025, 16, 64);
    const ring2Mat = new THREE.MeshStandardMaterial({
        color: statusColor,
        roughness: 0.25,
        metalness: 0.85,
        transparent: true,
        opacity: 0.8
    });
    const ring2 = new THREE.Mesh(ring2Geo, ring2Mat);
    ring2.rotation.y = Math.PI / 3;
    scene.add(ring2);

    // Studio Lighting
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.0);
    keyLight.position.set(3, 4, 4);
    scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(statusColor, 1.5);
    fillLight.position.set(-3, -3, 3);
    scene.add(fillLight);

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));

    const clock = new THREE.Clock();
    function animate() {
        requestAnimationFrame(animate);
        const elapsedTime = clock.getElapsedTime();

        sphere.rotation.y += 0.01;
        ring1.rotation.z += 0.014;
        ring2.rotation.x -= 0.012;

        // Gentle breathing pulse
        const pulse = 1.0 + Math.sin(elapsedTime * 2.5) * 0.04;
        sphere.scale.set(pulse, pulse, pulse);

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
 * 11. Auth Pages (Login & Register): Frosted Security Vault Prism
 */
function initAuth3DCube(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof THREE === 'undefined') return;

    const width = 110;
    const height = 110;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 50);
    camera.position.z = 4.2;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Brushed Platinum Chamfered Monolith
    const boxGeo = new THREE.BoxGeometry(1.3, 1.3, 1.3);
    const boxMat = new THREE.MeshStandardMaterial({
        color: 0x6366f1, // Royal Indigo
        emissive: 0x3730a3,
        emissiveIntensity: 0.2,
        roughness: 0.22,
        metalness: 0.88
    });
    const box = new THREE.Mesh(boxGeo, boxMat);
    scene.add(box);

    // Subtle Precision Orbital Frame
    const ringGeo = new THREE.TorusGeometry(1.8, 0.025, 16, 48);
    const ringMat = new THREE.MeshStandardMaterial({
        color: 0x38bdf8,
        roughness: 0.2,
        metalness: 0.95
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = Math.PI / 3;
    scene.add(ring);

    // Studio Lighting
    const light = new THREE.DirectionalLight(0xffffff, 2.0);
    light.position.set(3, 4, 4);
    scene.add(light);

    const rim = new THREE.DirectionalLight(0x818cf8, 1.2);
    rim.position.set(-3, -2, 2);
    scene.add(rim);

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));

    function animate() {
        requestAnimationFrame(animate);
        box.rotation.x += 0.009;
        box.rotation.y += 0.012;
        ring.rotation.z -= 0.015;
        renderer.render(scene, camera);
    }
    animate();
}

/**
 * 12. Copy Telegram Link Code to Clipboard
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
            copyBtn.innerHTML = '<i class="bi bi-check2 me-1"></i> Copied!';
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

/**
 * 13. Interactive Category Chart Switcher (Doughnut <-> Bar)
 */
function initChartSwitcher() {
    const doughnutBtn = document.getElementById('chart-view-doughnut');
    const barBtn = document.getElementById('chart-view-bar');
    if (!doughnutBtn || !barBtn || !window.categoryChart) return;

    doughnutBtn.addEventListener('click', () => {
        doughnutBtn.classList.add('active');
        barBtn.classList.remove('active');
        if (typeof window.switchCategoryChartView === 'function') {
            window.switchCategoryChartView('doughnut');
        }
    });

    barBtn.addEventListener('click', () => {
        barBtn.classList.add('active');
        doughnutBtn.classList.remove('active');
        if (typeof window.switchCategoryChartView === 'function') {
            window.switchCategoryChartView('bar');
        }
    });
}
