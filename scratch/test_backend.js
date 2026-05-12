const url = 'http://127.0.0.1:8000/healthz';
console.log(`Testing connection to ${url}...`);

fetch(url)
  .then(res => {
    console.log(`Status: ${res.status}`);
    return res.json();
  })
  .then(json => {
    console.log('Response:', json);
  })
  .catch(err => {
    console.error('Error:', err);
  });
