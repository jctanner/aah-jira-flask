// Define a custom date adapter
//class CustomDateAdapter extends Chart._adapters._date.adapters._date {
class CustomDateAdapter extends Chart._adapters._date {
  constructor(options) {
	super(options);
  }

  format(timestamp, format) {
	const date = new Date(timestamp);
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, '0');
	const day = String(date.getDate()).padStart(2, '0');

	return `${year}-${month}-${day}`;
  }

  parse(timestamp) {
	const [year, month, day] = timestamp.split('-').map(Number);

	return new Date(year, month - 1, day);
  }

  add(timestamp, amount, unit) {
	const date = new Date(timestamp);
	const adjustedDate = new Date(date.getTime());

	switch (unit) {
	  case 'day':
		adjustedDate.setDate(date.getDate() + amount);
		break;
	  // Add support for other units if needed
	}

	return adjustedDate;
  }

  diff(a, b, unit) {
	const diff = a.getTime() - b.getTime();

	switch (unit) {
	  case 'day':
		return Math.round(diff / (24 * 60 * 60 * 1000));
	  // Add support for other units if needed
	}

	return null;
  }
}

// Register the custom date adapter
//Chart.register(CustomDateAdapter);

function onLoad() {

    document.getElementById('burndown-chart').innerHTML = '<div class="spinner"></div>';

    fetch("/api/tickets_burndown", {
        method: "GET",
        headers: {'Content-Type': 'application/json'}, 
    }).then(res => res.json()).then(res => {
        console.log("Request complete! response:", res, typeof res);

        let newHTML = "";
        newHTML += '<h1>BURNDOWN</h1>';
        document.getElementById('burndown-chart').innerHTML = newHTML;

        const labels = Object.keys(res);
		console.log(labels);
        const values = Object.values(res);
		console.log(values);
		const ctx = document.getElementById('lineChart').getContext('2d');

		/*
        const lineChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Data',
                    data: values,
                    fill: false,
                    borderColor: 'rgb(75, 192, 192)',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'month'
                        }
                    },
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
		*/
        const lineChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'backlog count',
                    data: values,
                    fill: false,
                    borderColor: 'rgb(75, 192, 192)',
                    tension: 0.1
                }]
            }
		});

        console.log("done building burndown");
    });
};
