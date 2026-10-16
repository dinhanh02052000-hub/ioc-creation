// Nền chuyển động nhẹ phía sau nội dung. Dark mode: sao lấp lánh. Light mode:
// mây trôi. Đọc getTheme() mỗi khung hình nên đổi ngay khi bấm Sáng/Tối, không
// cần tải lại trang.
(function () {
  function initParticles() {
    let canvas = document.getElementById('particles-canvas');
    if (!canvas) {
      canvas = document.createElement('canvas');
      canvas.id = 'particles-canvas';
      document.body.prepend(canvas);
    }

    const ctx = canvas.getContext('2d');
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener('resize', () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    // ---- Dark mode: thiên hà đầy sao ----
    const STAR_COUNT = 380;
    const STAR_COLORS = ['#ffffff', '#dbe4ff', '#bcd0ff', '#e6d4ff', '#ffe9c7'];

    function makeStars() {
      const stars = [];
      for (let i = 0; i < STAR_COUNT; i++) {
        // ~35% sao tập trung quanh dải Ngân Hà chéo, còn lại rải đều.
        let x = Math.random() * width;
        let y = Math.random() * height;
        if (Math.random() < 0.35) {
          const along = Math.random();
          const spread = (Math.random() - 0.5) * height * 0.28;
          x = along * width;
          y = height * (0.85 - 0.7 * along) + spread;
        }
        const big = Math.random() < 0.06;
        stars.push({
          x, y,
          radius: big ? Math.random() * 1.2 + 1.3 : Math.random() * 1.0 + 0.25,
          baseAlpha: Math.random() * 0.45 + 0.3,
          twinkleSpeed: Math.random() * 0.03 + 0.006,
          twinklePhase: Math.random() * Math.PI * 2,
          driftX: Math.random() * 0.05 + 0.01,
          driftY: Math.random() * 0.02 + 0.004,
          color: STAR_COLORS[Math.floor(Math.random() * STAR_COLORS.length)],
          glow: big
        });
      }
      return stars;
    }

    // Tinh vân + dải Ngân Hà vẽ 1 lần ra canvas phụ rồi chép lại mỗi khung
    // hình, để không phải tính gradient lớn liên tục.
    let nebulaLayer = null;
    function makeNebula() {
      const layer = document.createElement('canvas');
      layer.width = width;
      layer.height = height;
      const g = layer.getContext('2d');

      g.save();
      g.translate(width * 0.5, height * 0.5);
      g.rotate(-Math.atan2(height * 0.7, width));
      const band = g.createLinearGradient(0, -height * 0.22, 0, height * 0.22);
      band.addColorStop(0, 'rgba(120, 100, 220, 0)');
      band.addColorStop(0.5, 'rgba(150, 130, 255, 0.16)');
      band.addColorStop(1, 'rgba(120, 100, 220, 0)');
      g.fillStyle = band;
      g.fillRect(-width, -height * 0.22, width * 2, height * 0.44);
      g.restore();

      const blobs = [
        { x: 0.2, y: 0.25, r: 0.32, c: '90, 70, 200' },
        { x: 0.75, y: 0.7, r: 0.36, c: '40, 110, 210' },
        { x: 0.55, y: 0.15, r: 0.22, c: '190, 70, 170' },
        { x: 0.1, y: 0.8, r: 0.25, c: '60, 60, 170' }
      ];
      blobs.forEach(b => {
        const rad = b.r * Math.max(width, height);
        const grad = g.createRadialGradient(b.x * width, b.y * height, 0, b.x * width, b.y * height, rad);
        grad.addColorStop(0, `rgba(${b.c}, 0.22)`);
        grad.addColorStop(1, `rgba(${b.c}, 0)`);
        g.fillStyle = grad;
        g.fillRect(0, 0, width, height);
      });
      return layer;
    }

    let shootingStar = null;
    function maybeSpawnShootingStar() {
      if (shootingStar || Math.random() > 0.004) return;
      shootingStar = { x: Math.random() * width * 0.8, y: Math.random() * height * 0.4, life: 0 };
    }

    function drawShootingStar() {
      if (!shootingStar) return;
      const s = shootingStar;
      s.x += 9;
      s.y += 4.5;
      s.life += 1;
      const alpha = Math.max(0, 1 - s.life / 40);
      const grad = ctx.createLinearGradient(s.x, s.y, s.x - 70, s.y - 35);
      grad.addColorStop(0, `rgba(255, 255, 255, ${alpha})`);
      grad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.globalAlpha = 1;
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(s.x - 70, s.y - 35);
      ctx.stroke();
      if (s.life > 40) shootingStar = null;
    }

    function drawStars(stars, t) {
      if (!nebulaLayer || nebulaLayer.width !== width || nebulaLayer.height !== height) {
        nebulaLayer = makeNebula();
      }
      ctx.globalAlpha = 1;
      ctx.drawImage(nebulaLayer, 0, 0);

      stars.forEach(s => {
        s.x += s.driftX;
        s.y += s.driftY;
        if (s.x > width) s.x = 0;
        if (s.y > height) s.y = 0;

        const alpha = s.baseAlpha + Math.sin(t * s.twinkleSpeed + s.twinklePhase) * 0.28;
        ctx.globalAlpha = Math.max(0, Math.min(1, alpha));
        ctx.fillStyle = s.color;
        if (s.glow) {
          ctx.shadowColor = s.color;
          ctx.shadowBlur = 8;
        }
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
        ctx.fill();
        if (s.glow) ctx.shadowBlur = 0;
      });

      maybeSpawnShootingStar();
      drawShootingStar();
    }

    // ---- Light mode: mây trôi dạt (mỗi cụm = vài hình tròn chồng lên nhau) ----
    const CLOUD_COUNT = 14;
    const CLOUD_PUFFS = [
      { dx: 0, dy: 0, r: 34 },
      { dx: -30, dy: 6, r: 24 },
      { dx: 30, dy: 6, r: 26 },
      { dx: -12, dy: -14, r: 20 },
      { dx: 16, dy: -12, r: 18 },
      { dx: 50, dy: 10, r: 16 }
    ];

    function makeClouds() {
      const clouds = [];
      for (let i = 0; i < CLOUD_COUNT; i++) {
        const scale = Math.random() * 0.8 + 0.7;
        clouds.push({
          x: Math.random() * width,
          y: Math.random() * height * 0.7 + height * 0.05,
          scale,
          speed: (Math.random() * 0.15 + 0.05) * scale,
          baseAlpha: Math.random() * 0.25 + 0.55, // đủ đậm để nổi rõ trên nền trời xanh
          bobPhase: Math.random() * Math.PI * 2,
          bobSpeed: Math.random() * 0.004 + 0.001
        });
      }
      return clouds;
    }

    // Vẽ trước khi vẽ mây để mây trông như đang trôi trước mặt trời.
    function drawSun() {
      const sunX = width * 0.82;
      const sunY = height * 0.16;
      const gradient = ctx.createRadialGradient(sunX, sunY, 0, sunX, sunY, 190);
      gradient.addColorStop(0, 'rgba(255, 236, 190, 0.9)');
      gradient.addColorStop(0.4, 'rgba(255, 224, 170, 0.35)');
      gradient.addColorStop(1, 'rgba(255, 224, 170, 0)');
      ctx.globalAlpha = 1;
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(sunX, sunY, 190, 0, Math.PI * 2);
      ctx.fill();

      ctx.globalAlpha = 0.9;
      ctx.fillStyle = '#fff3d8';
      ctx.beginPath();
      ctx.arc(sunX, sunY, 40, 0, Math.PI * 2);
      ctx.fill();
    }

    function drawClouds(clouds, t) {
      drawSun();

      clouds.forEach(c => {
        c.x += c.speed;
        const edge = 80 * c.scale;
        if (c.x - edge > width) c.x = -edge;

        const bob = Math.sin(t * c.bobSpeed + c.bobPhase) * 6;

        // Lớp bóng lệch dưới-phải trước khi phủ trắng lên, tạo độ dày cho mây.
        ctx.globalAlpha = c.baseAlpha * 0.35;
        ctx.fillStyle = '#c3d3e6';
        CLOUD_PUFFS.forEach(p => {
          ctx.beginPath();
          ctx.arc(c.x + p.dx * c.scale + 4, c.y + p.dy * c.scale + bob + 5, p.r * c.scale, 0, Math.PI * 2);
          ctx.fill();
        });

        ctx.globalAlpha = c.baseAlpha;
        ctx.fillStyle = '#ffffff';
        CLOUD_PUFFS.forEach(p => {
          ctx.beginPath();
          ctx.arc(c.x + p.dx * c.scale, c.y + p.dy * c.scale + bob, p.r * c.scale, 0, Math.PI * 2);
          ctx.fill();
        });
      });
    }

    let stars = makeStars();
    let clouds = makeClouds();
    let mode = typeof getTheme === 'function' ? getTheme() : 'dark';
    let t = 0;

    function animate() {
      t += 1;

      // getTheme() rẻ nên kiểm tra mỗi khung hình để đổi theme ngay lập tức.
      const currentTheme = typeof getTheme === 'function' ? getTheme() : 'dark';
      if (currentTheme !== mode) {
        mode = currentTheme;
      }

      ctx.clearRect(0, 0, width, height);
      if (mode === 'light') {
        drawClouds(clouds, t);
      } else {
        drawStars(stars, t);
      }

      requestAnimationFrame(animate);
    }

    animate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initParticles);
  } else {
    initParticles();
  }
})();
