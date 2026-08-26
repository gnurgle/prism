function bindSidebarEvents() {
    const listGroup = document.getElementById('path-list-group');
    if (!listGroup) return;

    document.querySelectorAll('.path-list-item').forEach(item => {
        item.replaceWith(item.cloneNode(true));
    });

    document.querySelectorAll('.path-list-item').forEach(item => {
        item.addEventListener('click', function(e) {
            if (e.target.tagName === 'BUTTON' || e.target.tagName === 'FORM' || e.target.closest('form')) return;

            const targetIndex = parseInt(this.getAttribute('data-path-index'));

            document.querySelectorAll('.path-list-item').forEach(li => {
                li.classList.remove('active');
                const deleteContainer = li.querySelector('.delete-container');
                if (deleteContainer) deleteContainer.style.display = 'none';
            });

            this.classList.add('active');
            const deleteContainer = this.querySelector('.delete-container');
            if (deleteContainer) deleteContainer.style.display = 'block';

            const svgObject = document.getElementById('svg-object');
            if (svgObject && svgObject.contentDocument) {
                const svgDoc = svgObject.contentDocument;
                let paths = svgDoc.querySelectorAll('path');
                if (paths.length === 0) paths = svgDoc.getElementsByTagNameNS('*', 'path');

                Array.from(paths).forEach((p, idx) => {
                    if (idx === targetIndex) {
                        p.setAttribute('stroke', 'red');
                        p.setAttribute('stroke-width', '20');
                    } else {
                        p.removeAttribute('stroke');
                        p.removeAttribute('stroke-width');
                    }
                });
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", function() {
    bindSidebarEvents();
});
