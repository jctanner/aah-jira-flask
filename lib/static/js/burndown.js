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

    queryString = window.location.search;
    const urlParams = new URLSearchParams(queryString);
    let projects = urlParams.getAll("project");

    if (projects.length === 0) {
        const url = new URL(window.location.href);
        url.searchParams.set("project", "AAH");
        history.replaceState(null, '', url.toString());
        projects = ['AAH'];
    }

    const start_date = urlParams.get("start");
    const end_date = urlParams.get("end");
    const frequency = urlParams.get("frequency");

    document.getElementById('burndown-chart').innerHTML = '<div class="spinner"></div>';

    const apiParams = new URLSearchParams();
    projects.forEach(value => {
        apiParams.append("project", value);
    });

    if ( start_date !== null ) {
        apiParams.append("start", start_date);
    }
    if ( end_date !== null ) {
        apiParams.append("end", end_date);
    }
    if ( frequency !== null ) {
        apiParams.append("frequency", frequency);
    }

    const apiString = apiParams.toString();
    const apiUrl = `/api/tickets_burndown/?${apiString}`;

    fetch(apiUrl, {
        method: "GET",
        headers: {'Content-Type': 'application/json'}, 
    }).then(res => res.json()).then(res => {
        console.log("Request complete! response:", res, typeof res);

        let newHTML = "";
        newHTML += '<h1>' + projects.join("/") + ' BURNDOWN' + '</h1>';
        document.getElementById('burndown-chart').innerHTML = newHTML;

        const labels = Object.keys(res['backlog']);
		console.log(labels);
        const values = Object.values(res['backlog']);
		console.log(values);

		const ctx = document.getElementById('lineChart').getContext('2d');

        const lineChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'backlog count',
                        data: values,
                        fill: false,
                        borderColor: 'rgb(75, 192, 192)',
                        tension: 0.1
                    },
                    {
                        label: 'opened',
                        data: Object.values(res['opened']),
                        fill: false,
                        borderColor: 'red',
                        tension: 0.1
                    },
                    {
                        label: 'closed',
                        data: Object.values(res['closed']),
                        fill: false,
                        borderColor: 'green',
                        tension: 0.1
                    },
                    {
                        label: 'moved_in',
                        data: Object.values(res['moved_in']),
                        fill: false,
                        borderColor: 'orange',
                        tension: 0.1
                    },
                    {
                        label: 'moved_out',
                        data: Object.values(res['moved_out']),
                        fill: false,
                        borderColor: 'purple',
                        tension: 0.1
                    },
                    {
                        label: 'enumerated_backlog',
                        data: Object.values(res['enumerated_backlog']),
                        fill: false,
                        borderColor: 'pink',
                        tension: 0.1
                    }
                ]
            }
		});

        console.log("done building burndown");
    });
};
