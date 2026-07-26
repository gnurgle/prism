function selectColor(val, hex, name) {
    document.getElementById('selected-color-input').value = val;
    
    const cleanHex = String(hex).replace('#', '').trim();
    
    const labelContainer = document.getElementById('selected-color-label');
    if (val) {
        labelContainer.innerHTML = `
            <span class="d-inline-block rounded border" style="width: 18px; height: 18px; background-color: #${cleanHex};"></span>
            ${name}
        `;
    } else {
        labelContainer.innerHTML = `<span class="text-muted">-- Select Color --</span>`;
    }
}
