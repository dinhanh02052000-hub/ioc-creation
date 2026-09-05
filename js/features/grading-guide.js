// ==== HƯỚNG DẪN LÀM BÀI (nút góc trên-trái world1.html / world2.html) ====
// Nội dung tĩnh, giống hệt trên cả 2 world - chỉ hiển thị hướng dẫn cách làm
// 2 câu hỏi mở (Distinction/Phân biệt và Application/Vận dụng), không liên
// quan tới dữ liệu level nên không cần tham số worldId.

function initGradingGuide() {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'world-map-guide-btn';
  btn.id = 'world-map-guide-btn';
  btn.title = 'Hướng dẫn bắt tay vào làm bài';
  btn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="9"/>
      <path d="M9.5 9.2a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 1.8-2.4 3.5"/>
      <path d="M12 17h.01"/>
    </svg>
    <span>Hướng dẫn làm bài</span>
  `;
  document.body.appendChild(btn);

  btn.addEventListener('click', openGradingGuideModal);
}

function openGradingGuideModal() {
  const overlay = document.createElement('div');
  overlay.className = 'grading-guide-overlay';
  overlay.id = 'grading-guide-overlay';

  overlay.innerHTML = `
    <div class="grading-guide-panel">
      <div class="grading-guide-header">
        <div class="grading-guide-title">Hướng dẫn bắt tay vào làm bài</div>
        <button type="button" class="grading-guide-close" id="grading-guide-close" title="Đóng">✕</button>
      </div>
      <div class="grading-guide-body">

        <p class="grading-guide-note">Được viết bằng tiếng Việt hoặc tiếng Anh đều được, KHÔNG bị trừ điểm vì dùng tiếng Việt - CHỈ RIÊNG câu đặt câu ở Phần 1 của Câu 2 (Application) là bắt buộc phải viết bằng tiếng Anh.</p>

        <h3>Câu 1: Phân biệt (Distinction)</h3>
        <p class="grading-guide-example-title">Ví dụ đề bài:</p>
        <blockquote>"The new gene-editing therapy had a lasting effect on patients' recovery time. If 'effect' were replaced with 'influence' or 'impact,' how would the sentence's focus or nuance change?"</blockquote>

        <p><strong>Cần làm gì?</strong> Câu này chủ yếu yêu cầu phân biệt sắc thái của các từ trong nhóm, trong đúng ngữ cảnh của câu. Nối các ý sau thành 1 đoạn văn hoàn chỉnh:</p>
        <ol>
          <li>Với mỗi từ có thể thay thế: nêu sắc thái/nghĩa của từ đó khác gì so với từ gốc, vì sao nó kém phù hợp hơn trong câu này.</li>
          <li>Vì sao từ gốc trong câu là lựa chọn phù hợp nhất.</li>
        </ol>
        <p class="grading-guide-note">Nếu 1 nhóm từ có quá nhiều từ dễ nhầm, chỉ cần giải thích 2-3 từ là được, không cần liệt kê hết cả nhóm.</p>

        <p class="grading-guide-example-title">Có thể viết thành đoạn như sau:</p>
        <blockquote>Replacing "effect" with "influence" or "impact" would slightly change the meaning of the sentence and make it less precise. "Influence" suggests a more gradual or indirect effect on someone's behavior or thoughts, which does not fit well with a specific clinical outcome. "Impact," meanwhile, emphasizes a strong or dramatic effect, making the sentence sound more forceful than necessary. Therefore, "effect" is the most appropriate word because it refers directly to a measurable result caused by the medical treatment, in this case, the gene-editing therapy.</blockquote>

        <h3>Câu 2: Vận dụng (Application)</h3>
        <p class="grading-guide-example-title">Ví dụ đề bài:</p>
        <blockquote>"After a short-video platform introduced an algorithm... average viewing time rose sharply and many users began sharing... In a full sentence, choose one word from the group to describe this situation and explain why it is the best choice over the other two."</blockquote>

        <p><strong>Cần làm gì?</strong> Khác câu 1, ở đây phải ĐẶT 1 từ vào chính tình huống được cho, không chỉ giải thích nghĩa. Viết liền thành 1 đoạn gồm 2 phần:</p>
        <ol>
          <li>Viết 1 câu <strong>tiếng Anh</strong> hoàn chỉnh mô tả tình huống, dùng đúng 1 từ trong nhóm (phần này bắt buộc tiếng Anh).</li>
          <li>Giải thích vì sao chọn từ đó, và vì sao các từ còn lại kém phù hợp hơn (phần này viết tiếng Việt hoặc tiếng Anh đều được).</li>
        </ol>
        <p class="grading-guide-note">Nếu 1 nhóm từ có quá nhiều từ, chỉ cần giải thích vì sao từ đã chọn tốt hơn 2-3 từ dễ nhầm nhất cũng được, không cần so sánh với toàn bộ nhóm.</p>

        <p class="grading-guide-example-title">Ví dụ:</p>
        <blockquote>The new algorithm had a profound impact on user engagement and platform activity. The word "impact" is the most appropriate choice because the situation describes a strong and noticeable change in user behavior, shown by the sharp increase in viewing time and sharing activity. "Effect" could also describe the result, but it is more general, while "influence" usually suggests a more gradual or indirect form of influence. Therefore, "impact" best captures the strong and immediate change caused by the new algorithm.</blockquote>

      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector('#grading-guide-close').addEventListener('click', close);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
}
