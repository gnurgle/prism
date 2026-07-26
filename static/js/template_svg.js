document.addEventListener("DOMContentLoaded", function() {
    const svgObject = document.getElementById('svg-object');
    if (!svgObject) return;

    svgObject.addEventListener('load', function() {
        const svgDoc = svgObject.contentDocument;
        if (!svgDoc) return;

        const svgElement = svgDoc.querySelector('svg');
        if (!svgElement) return;

        if (!svgElement.getAttribute('viewBox')) {
            svgElement.setAttribute('viewBox', '0 0 800 800');
        }

        let svgHeight = 800;
        const viewBox = svgElement.getAttribute('viewBox');
        if (viewBox) {
            const parts = viewBox.split(/[\s,]+/);
            if (parts.length === 4) {
                const vbH = parseFloat(parts[3]);
                if (!isNaN(vbH) && vbH > 0) svgHeight = vbH;
            }
        }

        const calculatedFontSize = svgHeight * 0.05;

        let paths = svgDoc.querySelectorAll('path');
        if (paths.length === 0) {
            paths = svgDoc.getElementsByTagNameNS('*', 'path');
        }

        const listGroup = document.getElementById('path-list-group');
        const fallbackMsg = document.getElementById('js-fallback-loading');
        
        if (fallbackMsg && paths.length > 0) {
            fallbackMsg.remove();

            Array.from(paths).forEach((path, index) => {
                const num = path.getAttribute('data-region-id') || path.getAttribute('data-number') || (index + 1);

                const li = document.createElement('li');
                li.className = 'list-group-item list-group-item-action path-list-item flex-column align-items-start mb-2';
                li.setAttribute('data-path-index', index);
                li.style.cursor = 'pointer';

                li.innerHTML = `
                    <div class="d-flex w-100 justify-content-between align-items-center">
                        <h6 class="mb-1 fw-bold">Path #${num}</h6>
                        <small class="text-muted">Index: ${index}</small>
                    </div>
                    <div class="delete-container mt-2" style="display: none;">
                        <form method="POST" class="d-inline">
                            <input type="hidden" name="region_id" value="${num}">
                            <button type="submit" class="btn btn-danger btn-sm w-100" onclick="return confirm('Are you sure you want to delete region ${num}?');">Delete This Path</button>
                        </form>
                    </div>
                `;
                listGroup.appendChild(li);
            });

            if (typeof bindSidebarEvents === 'function') {
                bindSidebarEvents();
            }
        }

        Array.from(paths).forEach((path, index) => {
            const num = path.getAttribute('data-region-id') || path.getAttribute('data-number') || (index + 1);

            if (!path.getAttribute('fill') || path.getAttribute('fill') === 'none') {
                path.setAttribute('fill', 'rgba(0,0,0,0)');
            }

            try {
                const bbox = path.getBBox();
                if (bbox && bbox.width > 0 && bbox.height > 0) {
                    const cx = bbox.x + bbox.width / 2;
                    const cy = bbox.y + bbox.height / 2;

                    const textEl = svgDoc.createElementNS("http://www.w3.org/2000/svg", "text");
                    textEl.setAttribute("x", cx);
                    textEl.setAttribute("y", cy);
                    textEl.setAttribute("fill", "#dc3545");
                    textEl.setAttribute("font-weight", "bold");
                    textEl.setAttribute("font-size", calculatedFontSize + "px");
                    textEl.setAttribute("text-anchor", "middle");
                    textEl.setAttribute("dominant-baseline", "central");
                    textEl.setAttribute("style", "pointer-events: none; user-select: none;");
                    textEl.textContent = num;

                    svgElement.appendChild(textEl);
                }
            } catch (err) {}
        });
    });
});
