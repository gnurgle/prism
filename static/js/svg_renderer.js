document.addEventListener("DOMContentLoaded", function() {
    const svgObject = document.getElementById('svg-object');
    if (svgObject) {
        svgObject.addEventListener('load', function() {
            renderSvgContent();
        });
    }
});

function renderSvgContent() {
    const svgObject = document.getElementById('svg-object');
    if (!svgObject) return;

    const svgDoc = svgObject.contentDocument;
    if (!svgDoc) return;

    const svgElement = svgDoc.querySelector('svg');
    if (!svgElement) return;

    if (!svgElement.getAttribute('viewBox')) {
        svgElement.setAttribute('viewBox', '0 0 800 800');
    }
    
    const viewBoxAttr = svgElement.getAttribute('viewBox');
    const viewBoxParts = viewBoxAttr.split(/[\s,]+/).map(parseFloat);
    const svgWidth = viewBoxParts.length === 4 ? viewBoxParts[2] : 800;
    const svgHeight = viewBoxParts.length === 4 ? viewBoxParts[3] : 800;

    let defs = svgElement.querySelector('defs');
    if (!defs) {
        defs = svgDoc.createElementNS("http://www.w3.org/2000/svg", "defs");
        svgElement.insertBefore(defs, svgElement.firstChild);
    } else {
        const oldPatterns = defs.querySelectorAll('pattern[id^="texture-pattern-"]');
        oldPatterns.forEach(p => p.remove());
        const oldFilters = defs.querySelectorAll('filter[id^="bump-filter-"]');
        oldFilters.forEach(f => f.remove());
    }

    let fontSize = svgHeight * 0.05;
    const paths = svgDoc.querySelectorAll('path');

    paths.forEach((path, index) => {
        const regionId = path.getAttribute('data-region-id') || path.getAttribute('data-number') || (index + 1);
        const comp = componentsData[regionId];
        
        const labelText = (comp && comp.COMPNUM !== undefined && comp.COMPNUM !== null && comp.COMPNUM !== '') ? comp.COMPNUM : regionId;
        let baseColor = (comp && comp.CHEX) ? '#' + comp.CHEX : '#cccccc';

        let trsValue = 75;
        if (comp && comp.GTRNSV !== undefined && comp.GTRNSV !== null && comp.GTRNSV !== '') {
            trsValue = parseFloat(comp.GTRNSV);
        }
        trsValue = Math.max(0, Math.min(100, trsValue));
        const shapeOpacity = (trsValue / 100).toFixed(2);

        let useImageFill = false;
        let imageUrl = '';
        if (currentAppearanceMode === 'image' && comp && comp.GLSIMG && comp.GLSIMG.trim() !== '') {
            useImageFill = true;
            imageUrl = glassImgBaseUrl + comp.GLSIMG.trim();
        }

        const hasTexture = !useImageFill && comp && comp.GLSTEX && comp.GLSTEX.trim() !== '';

        if (hasTexture || useImageFill) {
            const patternId = `texture-pattern-${regionId}-${currentAppearanceMode}-${comp ? (useImageFill ? comp.GLSIMG : comp.GLSTEX) : 'none'}`;
            
            const pattern = svgDoc.createElementNS("http://www.w3.org/2000/svg", "pattern");
            pattern.setAttribute("id", patternId);
            pattern.setAttribute("width", "1200");
            pattern.setAttribute("height", "1200");
            pattern.setAttribute("patternUnits", "userSpaceOnUse");
            
            if (useImageFill) {
                const imgWidth = svgWidth * 2;
                const imgHeight = svgHeight * 2;
                
                const centerX = (1200 - imgWidth) / 2;
                const centerY = (1200 - imgHeight) / 2;
                
                const maxOffsetX = svgWidth * 0.15;
                const maxOffsetY = svgHeight * 0.15;
                const randomOffsetX = (Math.random() * (maxOffsetX * 2)) - maxOffsetX;
                const randomOffsetY = (Math.random() * (maxOffsetY * 2)) - maxOffsetY;
                
                const finalX = centerX + randomOffsetX;
                const finalY = centerY + randomOffsetY;

                const imageFill = svgDoc.createElementNS("http://www.w3.org/2000/svg", "image");
                imageFill.setAttributeNS("http://www.w3.org/1999/xlink", "href", imageUrl);
                imageFill.setAttribute("href", imageUrl);
                imageFill.setAttribute("x", finalX);
                imageFill.setAttribute("y", finalY);
                imageFill.setAttribute("width", imgWidth);
                imageFill.setAttribute("height", imgHeight);
                imageFill.setAttribute("preserveAspectRatio", "none");
                imageFill.setAttribute("style", `opacity: ${shapeOpacity};`);
                pattern.appendChild(imageFill);
            } else {
                const baseRect = svgDoc.createElementNS("http://www.w3.org/2000/svg", "rect");
                baseRect.setAttribute("width", "1200");
                baseRect.setAttribute("height", "1200");
                baseRect.setAttribute("fill", baseColor);
                baseRect.setAttribute("opacity", shapeOpacity);
                pattern.appendChild(baseRect);

                const textureFilename = comp.GLSTEX.trim().toLowerCase() + '.jpg';
                const textureUrl = effectImgBaseUrl + textureFilename;

                const textureImage = svgDoc.createElementNS("http://www.w3.org/2000/svg", "image");
                textureImage.setAttributeNS("http://www.w3.org/1999/xlink", "href", textureUrl);
                textureImage.setAttribute("href", textureUrl);
                textureImage.setAttribute("width", "1200");
                textureImage.setAttribute("height", "1200");
                textureImage.setAttribute("preserveAspectRatio", "none");
                textureImage.setAttribute("style", `mix-blend-mode: multiply; opacity: ${shapeOpacity}; filter: grayscale(100%);`);
                pattern.appendChild(textureImage);
            }

            defs.appendChild(pattern);
            path.setAttribute('fill', `url(#${patternId})`);
            path.removeAttribute('fill-opacity');
        } else {
            path.setAttribute('fill', baseColor);
            path.setAttribute('fill-opacity', shapeOpacity);
        }

        if (hasTexture) {
            const textureFilterId = `bump-filter-${regionId}`;
            const filter = svgDoc.createElementNS("http://www.w3.org/2000/svg", "filter");
            filter.setAttribute("id", textureFilterId);
            filter.setAttribute("x", "-20%");
            filter.setAttribute("y", "-20%");
            filter.setAttribute("width", "140%");
            filter.setAttribute("height", "140%");

            const feColorMatrix = svgDoc.createElementNS("http://www.w3.org/2000/svg", "feColorMatrix");
            feColorMatrix.setAttribute("type", "matrix");
            feColorMatrix.setAttribute("values", "0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0.2126 0.7152 0.0722 0 0");
            filter.appendChild(feColorMatrix);

            const feDiffuse = svgDoc.createElementNS("http://www.w3.org/2000/svg", "feDiffuseLighting");
            feDiffuse.setAttribute("lighting-color", "#ffffff");
            feDiffuse.setAttribute("surfaceScale", "4");
            feDiffuse.setAttribute("result", "light");

            const feLight = svgDoc.createElementNS("http://www.w3.org/2000/svg", "feDistantLight");
            feLight.setAttribute("azimuth", "45");
            feLight.setAttribute("elevation", "60");
            feDiffuse.appendChild(feLight);
            filter.appendChild(feDiffuse);

            const feBlend = svgDoc.createElementNS("http://www.w3.org/2000/svg", "feBlend");
            feBlend.setAttribute("mode", "multiply");
            feBlend.setAttribute("in", "SourceGraphic");
            feBlend.setAttribute("in2", "light");
            feBlend.setAttribute("result", "blended");
            filter.appendChild(feBlend);

            const feComposite = svgDoc.createElementNS("http://www.w3.org/2000/svg", "feComposite");
            feComposite.setAttribute("in", "blended");
            feComposite.setAttribute("in2", "SourceAlpha");
            feComposite.setAttribute("operator", "in");
            filter.appendChild(feComposite);

            defs.appendChild(filter);
            path.style.filter = `url(#${textureFilterId})`;
        } else {
            path.style.filter = 'none';
        }

        path.removeAttribute('opacity');
        path.setAttribute('stroke', '#222222');      
        path.setAttribute('stroke-width', currentStrokeWidth);    
        path.setAttribute('stroke-linejoin', 'round'); 
        path.style.cursor = 'pointer';

        const newPath = path.cloneNode(true);
        path.parentNode.replaceChild(newPath, path);

        newPath.addEventListener('click', function(e) {
            e.stopPropagation();
            populateSidebar(regionId);
        });

        const existingText = svgElement.querySelector(`text[data-region-label="${regionId}"]`);

        if (!existingText) {
            try {
                const bbox = newPath.getBBox();
                if (bbox && bbox.width > 0 && bbox.height > 0) {
                    const cx = bbox.x + bbox.width / 2;
                    const cy = bbox.y + bbox.height / 2;

                    const textEl = svgDoc.createElementNS("http://www.w3.org/2000/svg", "text");
                    textEl.setAttribute("data-region-label", regionId);
                    textEl.setAttribute("x", cx);
                    textEl.setAttribute("y", cy);
                    textEl.setAttribute("fill", "#000000");
                    textEl.setAttribute("stroke", "#ffffff");
                    textEl.setAttribute("stroke-width", "3px");
                    textEl.setAttribute("stroke-linejoin", "round");
                    textEl.setAttribute("paint-order", "stroke fill");
                    textEl.setAttribute("font-weight", "bold");
                    textEl.setAttribute("font-size", fontSize + "px");
                    textEl.setAttribute("text-anchor", "middle");
                    textEl.setAttribute("dominant-baseline", "central");
                    textEl.setAttribute("style", "pointer-events: none; user-select: none;");
                    textEl.textContent = labelText;

                    svgElement.appendChild(textEl);
                }
            } catch (err) {
                console.warn("Could not calculate bounding box for path element", err);
            }
        }
    });
}
