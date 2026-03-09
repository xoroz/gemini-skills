source .env
curl -s -X POST -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" -d '{"site_slug":"panetteria-stefania","target_selector":"h1","prompt":"Make the title very short and punchy in Italian"}' https://dev.texngo.it/modify-site
