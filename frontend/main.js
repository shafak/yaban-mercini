document.addEventListener('DOMContentLoaded', () => {
    // FAQ Toggle
    const faqItems = document.querySelectorAll('.faq-item');
    faqItems.forEach(item => {
        const question = item.querySelector('.faq-question');
        question.addEventListener('click', () => {
            const answer = item.querySelector('.faq-answer');
            const isOpen = answer.style.display === 'block';
            
            // Close all others
            faqItems.forEach(i => i.querySelector('.faq-answer').style.display = 'none');
            
            answer.style.display = isOpen ? 'none' : 'block';
        });
    });

    // Simple Scroll Animation (Reveal on Scroll)
    const observerOptions = {
        threshold: 0.1
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, observerOptions);

    const revealElements = document.querySelectorAll('.step-card, .feature-card, .stat-item');
    revealElements.forEach(el => {
        el.classList.add('reveal');
        observer.observe(el);
    });
});
