let bgPosX = 50;
let bgPosY = 50;
let isDraggingJoystick = false;
let startMouseX = 0;
let startMouseY = 0;
let startBgPosX = 50;
let startBgPosY = 50;

function setSvgBackground(type) {
    const wrapper = document.getElementById('svg-wrapper');
    const joystick = document.getElementById('bg-joystick');
    
    document.getElementById('bg-white-btn').classList.remove('active', 'btn-secondary');
    document.getElementById('bg-outside-btn').classList.remove('active', 'btn-secondary');
    document.getElementById('bg-transparent-btn').classList.remove('active', 'btn-secondary');

    if (type === 'white') {
        wrapper.style.backgroundColor = '#ffffff';
        wrapper.style.backgroundImage = 'none';
        joystick.style.display = 'none';
        resetJoystick();
        document.getElementById('bg-white-btn').classList.add('active', 'btn-secondary');
    } else if (type === 'outside') {
        wrapper.style.backgroundColor = 'transparent';
        wrapper.style.backgroundImage = `url('${outsideBgUrl}')`;
        wrapper.style.backgroundSize = 'auto 150%';
        wrapper.style.backgroundPosition = `${bgPosX}% ${bgPosY}%`;
        joystick.style.display = 'flex';
        document.getElementById('bg-outside-btn').classList.add('active', 'btn-secondary');
    } else if (type === 'transparent') {
        wrapper.style.backgroundColor = 'transparent';
        wrapper.style.backgroundImage = 'none';
        joystick.style.display = 'none';
        resetJoystick();
        document.getElementById('bg-transparent-btn').classList.add('active', 'btn-secondary');
    }
}

function resetJoystick() {
    isDraggingJoystick = false;
    const knob = document.getElementById('joystick-knob');
    if (knob) knob.style.transform = `translate(0px, 0px)`;
    const svgObject = document.getElementById('svg-object');
    if (svgObject) svgObject.style.pointerEvents = 'auto';
}

document.addEventListener("DOMContentLoaded", function() {
    const joystick = document.getElementById('bg-joystick');
    const knob = document.getElementById('joystick-knob');
    const wrapper = document.getElementById('svg-wrapper');
    const svgObject = document.getElementById('svg-object');

    function startDrag(clientX, clientY) {
        isDraggingJoystick = true;
        joystick.style.cursor = 'grabbing';
        startMouseX = clientX;
        startMouseY = clientY;
        startBgPosX = bgPosX;
        startBgPosY = bgPosY;

        if (svgObject) svgObject.style.pointerEvents = 'none';
    }

    function moveDrag(clientX, clientY) {
        if (!isDraggingJoystick) return;

        const rect = joystick.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        let dx = clientX - centerX;
        let dy = clientY - centerY;

        const maxRadius = (rect.width / 2) - 15;
        const distance = Math.sqrt(dx * dx + dy * dy);

        let visualDx = dx;
        let visualDy = dy;
        if (distance > maxRadius && distance > 0) {
            visualDx = (dx / distance) * maxRadius;
            visualDy = (dy / distance) * maxRadius;
        }

        const mouseDeltaX = clientX - startMouseX;
        const mouseDeltaY = clientY - startMouseY;

        bgPosX = Math.max(0, Math.min(100, startBgPosX - (mouseDeltaX * 0.15)));
        bgPosY = Math.max(0, Math.min(100, startBgPosY - (mouseDeltaY * 0.15)));

        wrapper.style.backgroundPosition = `${bgPosX}% ${bgPosY}%`;
        knob.style.transform = `translate(${visualDx}px, ${visualDy}px)`;
    }

    function endDrag() {
        if (isDraggingJoystick) {
            isDraggingJoystick = false;
            joystick.style.cursor = 'grab';
            knob.style.transform = `translate(0px, 0px)`;

            if (svgObject) svgObject.style.pointerEvents = 'auto';
        }
    }

    if (joystick) {
        joystick.addEventListener('mousedown', function(e) {
            if (e.button !== 0) return;
            startDrag(e.clientX, e.clientY);
            e.preventDefault();
        });
    }

    document.addEventListener('mousemove', function(e) {
        moveDrag(e.clientX, e.clientY);
    });

    document.addEventListener('mouseup', function(e) {
        endDrag();
    });

    if (joystick) {
        joystick.addEventListener('touchstart', function(e) {
            if (e.touches.length > 0) {
                startDrag(e.touches[0].clientX, e.touches[0].clientY);
                e.preventDefault();
            }
        }, { passive: false });
    }

    document.addEventListener('touchmove', function(e) {
        if (e.touches.length > 0) {
            moveDrag(e.touches[0].clientX, e.touches[0].clientY);
        }
    }, { passive: true });

    document.addEventListener('touchend', function(e) {
        endDrag();
    });
});
