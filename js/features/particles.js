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

    // ---- Dark mode: sao lấp lánh ----
    const STAR_COUNT = 90;
    function makeStars() {
      const stars = [];
      for (let i = 0; i < STAR_COUNT; i++) {
        stars.push({
          x: Math.random() * width,
          y: Math.random() * height,
          radius: Math.random() * 1.1 + 0.3,
          baseAlpha: Math.random() * 0.4 + 0.25,
          twinkleSpeed: Math.random() * 0.02 + 0.006,
          twinklePhase: Math.random() * Math.PI * 2,
          driftX: Math.random() * 0.06 + 0.015,
          driftY: Math.random() * 0.03 + 0.005
        });
      }
      return stars;
    }

    function drawStars(stars, t) {
      stars.forEach(s => {
        s.x += s.driftX;
        s.y += s.driftY;
        if (s.x > width) s.x = 0;
        if (s.y > height) s.y = 0;

        const alpha = s.baseAlpha + Math.sin(t * s.twinkleSpeed + s.twinklePhase) * 0.25;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
        ctx.fillStyle = '#dbe4ff';
        ctx.globalAlpha = Math.max(0, Math.min(1, alpha));
        ctx.fill();
      });
    }

    // ---- Light mode: mây trôi dạt (mỗi cụm = vài hình tròn chồng lên nhau) ----
    const CLOUD_COUNT = 7;
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
      const gradient = ctx.createRadialGradient(sunX, sunY, 0, sunX, sunY, 140);
      gradient.addColorStop(0, 'rgba(255, 236, 190, 0.9)');
      gradient.addColorStop(0.4, 'rgba(255, 224, 170, 0.35)');
      gradient.addColorStop(1, 'rgba(255, 224, 170, 0)');
      ctx.globalAlpha = 1;
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(sunX, sunY, 140, 0, Math.PI * 2);
      ctx.fill();

      ctx.globalAlpha = 0.9;
      ctx.fillStyle = '#fff3d8';
      ctx.beginPath();
      ctx.arc(sunX, sunY, 30, 0, Math.PI * 2);
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
