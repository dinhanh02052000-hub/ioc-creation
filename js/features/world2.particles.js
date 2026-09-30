// Tuyết rơi nhẹ trên bản đồ World 2 (theme ice). pointer-events: none ở CSS
// nên không chặn click.
(function () {
  function initSnow() {
    let canvas = document.getElementById('world2-particles-canvas');
    if (!canvas) {
      canvas = document.createElement('canvas');
      canvas.id = 'world2-particles-canvas';
      document.body.appendChild(canvas);
    }

    const ctx = canvas.getContext('2d');
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener('resize', () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    const SNOW_COUNT = 55;
    const flakes = [];

    function makeFlake(scatterY) {
      return {
        x: Math.random() * width,
        baseX: 0,
        y: scatterY ? Math.random() * height : -10,
        radius: Math.random() * 2.4 + 1,
        fallSpeed: Math.random() * 0.55 + 0.3,
        swaySpeed: Math.random() * 0.012 + 0.004,
        swayAmount: Math.random() * 25 + 8,
        swayPhase: Math.random() * Math.PI * 2,
        alpha: Math.random() * 0.5 + 0.4
      };
    }

    for (let i = 0; i < SNOW_COUNT; i++) {
      const flake = makeFlake(true);
      flake.baseX = flake.x;
      flakes.push(flake);
    }

    let t = 0;
    let running = true;

    function animate() {
      if (!document.body.contains(canvas)) { running = false; return; }
      t += 1;
      ctx.clearRect(0, 0, width, height);

      flakes.forEach(flake => {
        flake.y += flake.fallSpeed;
        flake.x = flake.baseX + Math.sin(t * flake.swaySpeed + flake.swayPhase) * flake.swayAmount;

        if (flake.y > height + 10) {
          flake.y = -10;
          flake.baseX = Math.random() * width;
        }

        ctx.beginPath();
        ctx.arc(flake.x, flake.y, flake.radius, 0, Math.PI * 2);
        ctx.fillStyle = '#eaf4ff';
        ctx.globalAlpha = flake.alpha;
        ctx.fill();
      });

      if (running) requestAnimationFrame(animate);
    }

    animate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSnow);
  } else {
    initSnow();
  }
})();
