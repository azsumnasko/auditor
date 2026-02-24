document.addEventListener('DOMContentLoaded', () => {
    // Example data
    const data = {
        labels: ['January', 'February', 'March', 'April', 'May', 'June', 'July'],
        datasets: [{
            label: 'Revenue',
            backgroundColor: 'rgba(75, 192, 192, 0.4)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1,
            data: [65, 59, 80, 81, 56, 55, 40]
        }]
    };

    // Get the context of the canvas element we want to select
    const ctx = document.getElementById('myChart').getContext('2d');

    // Create the chart
    new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
});
