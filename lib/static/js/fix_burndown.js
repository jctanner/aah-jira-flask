// Define a custom date adapter
//class CustomDateAdapter extends Chart._adapters._date.adapters._date {
class CustomDateAdapter extends Chart._adapters._date {
  constructor(options) {
    super(options);
  }

  format(timestamp, format) {
    const date = new Date(timestamp);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");

    return `${year}-${month}-${day}`;
  }

  parse(timestamp) {
    const [year, month, day] = timestamp.split("-").map(Number);

    return new Date(year, month - 1, day);
  }

  add(timestamp, amount, unit) {
    const date = new Date(timestamp);
    const adjustedDate = new Date(date.getTime());

    switch (unit) {
      case "day":
        adjustedDate.setDate(date.getDate() + amount);
        break;
      // Add support for other units if needed
    }

    return adjustedDate;
  }

  diff(a, b, unit) {
    const diff = a.getTime() - b.getTime();

    switch (unit) {
      case "day":
        return Math.round(diff / (24 * 60 * 60 * 1000));
      // Add support for other units if needed
    }

    return null;
  }
}

function doSearch() {
  console.log("start search ...");
  const searchBox = document.getElementById("search-box");
  const query = searchBox.value;

  /*
          const payload = {
              query: query
          }
      
          axios.post('/api/tickets', payload)
              .then(response => {
                  console.log(response);
                  buildTable(response.data);
              })
              .catch(error => {
                  console.error(error);
              });
          */

  buildBurnDown(query);
}

function getRandomColor() {
  const letters = "0123456789ABCDEF";
  let color = "#";
  for (let i = 0; i < 6; i++) {
    color += letters[Math.floor(Math.random() * 16)];
  }
  return color;
}

function buildBurnDown(query) {
  console.log("build burndown started ...");

  queryString = window.location.search;
  const urlParams = new URLSearchParams(queryString);
  let projects = urlParams.getAll("project");
  let versions = urlParams.getAll("version");

  // force to AAH if no project given ...
  if (projects.length === 0) {
    const url = new URL(window.location.href);
    url.searchParams.set("project", "AAH");
    history.replaceState(null, "", url.toString());
    projects = ["AAH"];
  }

  const apiParams = new URLSearchParams();
  projects.forEach((value) => {
    apiParams.append("project", value);
  });
  if (versions.length > 0) {
    versions.forEach((version) => {
      apiParams.append("version", version);
    });
  }

  /*
  const start_date = urlParams.get("start");
  const end_date = urlParams.get("end");
  const frequency = urlParams.get("frequency");
  let jql = query;
  if (jql === null) {
    jql = urlParams.get("jql");
  }

  if (start_date !== null) {
    apiParams.append("start", start_date);
  }
  if (end_date !== null) {
    apiParams.append("end", end_date);
  }
  if (frequency !== null) {
    apiParams.append("frequency", frequency);
  }
  if (jql !== null) {
    apiParams.append("jql", jql);
  }
  */

  document.getElementById("burndown-chart").innerHTML =
    '<div class="spinner"></div>';

  const apiString = apiParams.toString();
  const apiUrl = `/api/fixversion_burndown/?${apiString}`;

  fetch(apiUrl, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  })
    .then((res) => res.json())
    .then((res) => {
      console.log("Request complete! response:", res, typeof res);
      jsonData = res;

      let newHTML = "";
      newHTML += "<h1>" + projects.join("/") + " BURNDOWN" + "</h1>";
      document.getElementById("burndown-chart").innerHTML = newHTML;

      const labels = [];
      const datasets = [];

      // Extract unique dates for labels
      Object.values(jsonData).forEach((obj) => {
        Object.keys(obj).forEach((date) => {
          if (!labels.includes(date)) {
            labels.push(date);
          }
        });
      });

      // Sort labels to ensure chronological order
      labels.sort();

      // Convert labels to timestamps
      const timestamps = labels.map((label) => new Date(label).getTime());

      Object.keys(jsonData).forEach((version) => {
        const data = [];
        labels.forEach((label) => {
          data.push({
            x: new Date(label).getTime(),
            y: jsonData[version][label] || 0,
          });
        });
        datasets.push({
          label: `Version ${version}`,
          data: data,
          fill: false,
          borderColor: getRandomColor(),
          tension: 0.1,
        });
      });

      console.log("labels", labels);
      console.log("datasets", datasets);

      const ctx = document.getElementById("lineChart").getContext("2d");

      const lineChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: labels,
          datasets: datasets,
        },
        options: {
          scales: {
            x: {
              type: "time",
              time: {
                unit: "month",
              },
              title: {
                display: true,
                text: "Date",
              },
            },
            y: {
              title: {
                display: true,
                text: "Count",
              },
            },
          },
        },
      });

      console.log("done building burndown");
    });
}

function onLoad() {
  buildBurnDown(null);
}
