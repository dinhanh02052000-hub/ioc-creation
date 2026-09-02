// Lá rơi nhẹ nhàng phía trên bản đồ World 1 (rừng huyền bí) - mật độ thấp,
// tông xanh lá/nâu/vàng đồng bộ theme forest, không chặn click (pointer-events:
// none ở CSS), tự dừng vẽ khi canvas không còn trên trang (world2 không load
// file này nên không xung đột).
(function () {
  function initLeaves() {
    let canvas = document.getElementById('world1-particles-canvas');
    if (!canvas) {
      canvas = document.createElement('canvas');
      canvas.id = 'world1-particles-canvas';
      document.body.appendChild(canvas);
    }

    const ctx = canvas.getContext('2d');
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener('resize', () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    const LEAF_COLORS = ['#6b9c5a', '#8faf4e', '#b98a3c', '#c9a53f', '#4f7a42'];
    const LEAF_COUNT = 26;
    const leaves = [];

    function makeLeaf(scatterY) {
      return {
        x: Math.random() * width,
        baseX: 0,
        y: scatterY ? Math.random() * height : -20,
        size: Math.random() * 7 + 6,
        color: LEAF_COLORS[Math.floor(Math.random() * LEAF_COLORS.length)],
        fallSpeed: Math.random() * 0.45 + 0.3,
        swaySpeed: Math.random() * 0.015 + 0.006,
        swayAmount: Math.random() * 30 + 15,
        swayPhase: Math.random() * Math.PI * 2,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.03
      };
    }

    for (let i = 0; i < LEAF_COUNT; i++) {
      const leaf = makeLeaf(true);
      leaf.baseX = leaf.x;
      leaves.push(leaf);
    }

    let t = 0;
    let running = true;

    function animate() {
      if (!document.body.contains(canvas)) { running = false; return; }
      t += 1;
      ctx.clearRect(0, 0, width, height);

      leaves.forEach(leaf => {
        leaf.y += leaf.fallSpeed;
        leaf.x = leaf.baseX + Math.sin(t * leaf.swaySpeed + leaf.swayPhase) * leaf.swayAmount;
        leaf.rotation += leaf.rotationSpeed;

        if (leaf.y > height + 20) {
          leaf.y = -20;
          leaf.baseX = Math.random() * width;
        }

        ctx.save();
        ctx.translate(leaf.x, leaf.y);
        ctx.rotate(leaf.rotation);
        ctx.fillStyle = leaf.color;
        ctx.globalAlpha = 0.75;
        ctx.beginPath();
        ctx.ellipse(0, 0, leaf.size, leaf.size * 0.55, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      });

      if (running) requestAnimationFrame(animate);
    }

    animate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLeaves);
  } else {
    initLeaves();
  }
})();
