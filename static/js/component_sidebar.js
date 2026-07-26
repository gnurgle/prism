let currentAppearanceMode = 'chex'; // 'chex' or 'image'
let currentStrokeWidth = 2; // Default stroke width

function setAppearanceMode(mode) {
    currentAppearanceMode = mode;
    
    const chexBtn = document.getElementById('mode-chex-btn');
    const imgBtn = document.getElementById('mode-img-btn');
    
    if (mode === 'chex') {
        chexBtn.classList.add('active', 'btn-secondary');
        chexBtn.classList.remove('btn-light');
        imgBtn.classList.remove('active', 'btn-secondary');
        imgBtn.classList.add('btn-light');
    } else {
        imgBtn.classList.add('active', 'btn-secondary');
        imgBtn.classList.remove('btn-light');
        chexBtn.classList.remove('active', 'btn-secondary');
        chexBtn.classList.add('btn-light');
    }

    if (typeof renderSvgContent === 'function') {
        renderSvgContent();
    }
}

function setStrokeWidth(width) {
    currentStrokeWidth = width;

    const thinBtn = document.getElementById('stroke-thin-btn');
    const thickBtn = document.getElementById('stroke-thick-btn');

    if (width <= 2) {
        thinBtn.classList.add('active', 'btn-secondary', 'text-white');
        thinBtn.classList.remove('btn-light', 'text-dark');
        thickBtn.classList.remove('active', 'btn-secondary', 'text-white');
        thickBtn.classList.add('btn-light', 'text-dark');
    } else {
        thickBtn.classList.add('active', 'btn-secondary', 'text-white');
        thickBtn.classList.remove('btn-light', 'text-dark');
        thinBtn.classList.remove('active', 'btn-secondary', 'text-white');
        thinBtn.classList.add('btn-light', 'text-dark');
    }

    if (typeof renderSvgContent === 'function') {
        renderSvgContent();
    }
}

function populateSidebar(regionId) {
    const comp = componentsData[regionId];
    const noSelectionMsg = document.getElementById('no-selection-msg');
    const componentForm = document.getElementById('component-form');

    if (!comp) {
        alert(`No component configuration found for Region ID: ${regionId}. Please build components first.`);
        return;
    }

    noSelectionMsg.style.display = 'none';
    componentForm.style.display = 'block';

    document.getElementById('comp_id').value = comp.COMPID;
    document.getElementById('comp_num').value = comp.COMPNUM;
    document.getElementById('comp_name').value = comp.COMPNAME;
    document.getElementById('comp_len').value = comp.COMPLEN;
    document.getElementById('comp_wid').value = comp.COMPWID;
    document.getElementById('glass_id').value = comp.GLASSID;
    document.getElementById('isscrap').checked = comp.ISSCRAP === 1;
    document.getElementById('isgrain').checked = comp.ISGRAIN === 1;
}
