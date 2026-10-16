// Trang "Giới thiệu" - gồm phần Meet the Founder (chuyển từ Home sang) và
// tóm tắt cách IOC hoạt động. Nội dung tĩnh, không có tương tác/API riêng.

const ABOUT_HOW_IT_WORKS = [
  { icon: 'bookOpen', title: 'Học từ', desc: 'AI dạy nhóm từ mới dựa trên knowledge base cố định của level đó.' },
  { icon: 'chartLine', title: 'Làm bài 20 câu', desc: 'Trắc nghiệm điền từ để đo mức độ nhận diện mặt chữ.' },
  { icon: 'user', title: 'Tự chấm độ tự tin', desc: 'Bạn tự đánh giá mình hiểu từ đến đâu, trước khi làm phần khó hơn.' },
  { icon: 'lightbulb', title: 'Làm bài Phân biệt và Vận dụng', desc: 'Hai câu hỏi mở: phân biệt sắc thái các từ gần nghĩa, rồi dùng từ vào một tình huống thực tế. AI chấm theo rubric.' },
  { icon: 'map', title: 'So sánh và tìm Gap', desc: 'Hệ thống so độ tự tin với năng lực thực đo được, chỉ ra khoảng cách (Gap).' },
];

function renderAbout() {
  const stepsHtml = ABOUT_HOW_IT_WORKS.map((s, i) => `
    <div class="about-step">
      <div class="about-step-icon">${icon(s.icon, 22)}</div>
      <div class="about-step-num">Bước ${i + 1}</div>
      <div class="about-step-title">${s.title}</div>
      <p class="about-step-desc">${s.desc}</p>
    </div>
  `).join('');

  return `
    <div class="about-page">
      <h1 class="analysis-heading">Giới thiệu</h1>
      <p class="page-desc">Đội ngũ phát triển IOC và cách hệ thống hoạt động.</p>

      <div class="card about-card">
        <div class="card-header"><span class="card-title">Đội ngũ phát triển</span></div>
        <div class="founder-row">
          <div class="founder-member">
            <img src="assets/images/founder-dinhanh.jpg" alt="Đinh Việt Anh" class="founder-avatar">
            <div class="founder-role">Trưởng nhóm</div>
            <div class="founder-name">Đinh Việt Anh</div>
          </div>
          <div class="founder-member">
            <img src="assets/images/founder-tuan.jpg" alt="Nguyễn Minh Tuấn" class="founder-avatar">
            <div class="founder-role">Thành viên</div>
            <div class="founder-name">Nguyễn Minh Tuấn</div>
          </div>
          <div class="founder-member">
            <img src="assets/images/founder-hanlinh.jpg" alt="Hán Linh Linh" class="founder-avatar">
            <div class="founder-role">Thành viên</div>
            <div class="founder-name">Hán Linh Linh</div>
          </div>
        </div>
        <div class="dev-divider"></div>
        <blockquote class="dev-quote">
          Cảm ơn bạn đã trải nghiệm IOC! Mong rằng hệ thống của chúng mình sẽ luôn là người bạn đồng hành đáng tin cậy, giúp bạn làm chủ kiến thức mỗi ngày.
          <footer>— Lời nhắn từ tác giả <span class="motto">See you Beyond, Improve Truly.</span></footer>
        </blockquote>
      </div>

      <div class="card about-card">
        <div class="card-header"><span class="card-title">IOC hoạt động thế nào</span></div>
        <div class="about-steps">${stepsHtml}</div>
      </div>
    </div>
  `;
}
