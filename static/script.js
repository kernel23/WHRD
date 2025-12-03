function updateStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            document.getElementById('mode').textContent = data.mode;
            document.getElementById('stage').textContent = data.stage;
            document.getElementById('temperature').textContent = data.temperature.toFixed(1);
            document.getElementById('target_temp').textContent = data.target_temp.toFixed(1);
            document.getElementById('max_temp').textContent = data.max_temp.toFixed(1);
            document.getElementById('humidity').textContent = data.humidity.toFixed(1);
            document.getElementById('fan_on').textContent = data.fan_on ? 'ON' : 'OFF';
            document.getElementById('dehumidifier_on').textContent = data.dehumidifier_on ? 'ON' : 'OFF';
            document.getElementById('fan_on_2').textContent = data.fan_on_2 ? 'ON' : 'OFF';
            document.getElementById('dehumidifier_on_2').textContent = data.dehumidifier_on_2 ? 'ON' : 'OFF';
            document.getElementById('buzzer_on').textContent = data.buzzer_on ? 'ON' : 'OFF';

            const uptime_hours = Math.floor(data.uptime / 3600);
            const uptime_minutes = Math.floor((data.uptime % 3600) / 60);
            const uptime_seconds = Math.floor(data.uptime % 60);
            document.getElementById('uptime').textContent = `${uptime_hours.toString().padStart(2, '0')}:${uptime_minutes.toString().padStart(2, '0')}:${uptime_seconds.toString().padStart(2, '0')}`;
            document.getElementById('current_time').textContent = data.current_time;

            if (data.mode === 'AUTO') {
                const minutes = Math.floor(data.remaining_seconds / 60);
                const seconds = Math.floor(data.remaining_seconds % 60);
                document.getElementById('next_temp_increase').textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            } else {
                document.getElementById('next_temp_increase').textContent = 'N/A';
            }

            // Disable manual controls in AUTO mode
            const isAutoMode = data.mode === 'AUTO';
            document.getElementById('toggle-fan').disabled = isAutoMode;
            document.getElementById('toggle-dehumidifier').disabled = isAutoMode;
        });
}

document.getElementById('toggle-mode').addEventListener('click', () => {
    fetch('/api/mode', { method: 'POST' })
        .then(() => updateStatus());
});

document.getElementById('next-stage').addEventListener('click', () => {
    fetch('/api/stage', { method: 'POST' })
        .then(() => updateStatus());
});

document.getElementById('toggle-fan').addEventListener('click', () => {
    fetch('/api/fan', { method: 'POST' })
        .then(() => updateStatus());
});

document.getElementById('toggle-dehumidifier').addEventListener('click', () => {
    fetch('/api/dehumidifier', { method: 'POST' })
        .then(() => updateStatus());
});

setInterval(updateStatus, 2000);
updateStatus();