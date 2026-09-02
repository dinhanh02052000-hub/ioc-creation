// Dải sao trôi nhẹ phía sau nội dung — chỉ để gợi không khí "công nghệ",
// cố tình giữ mật độ thấp và không dùng glow/màu sắc rực rỡ để tránh
// trông giống nền AI-generated mặc định.
(function () {
  function initStars() {
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

    const STAR_COUNT = 90;
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

    let t = 0;

    function animate() {
      t += 1;
      ctx.clearRect(0, 0, width, height);

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

      requestAnimationFrame(animate);
    }

    animate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStars);
  } else {
    initStars();
  }
})();
