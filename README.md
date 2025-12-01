Analytics Agent — AI-Powered Data Understanding & Transformation

Welcome to Analytics Agent, an AI-driven analytics platform built to intelligently analyze uploaded Excel/CSV datasets, understand their structure, and transform them based on natural-language requests.

It combines:

Python data processing

Advanced EDA (Exploratory Data Analysis)

OpenAI GPT-4.1-mini for reasoning

A modern Streamlit interface

Custom Excel/CSV output generation

This makes it ideal for:

Federal contracting analysis

Procurement intelligence

Business development

Consulting & analytics work

Any workflow requiring upload → AI understanding → filtered export

Features
 AI Dataset Understanding

When a user uploads a dataset, the system automatically:

Inspects columns

Collects unique values

Detects date/type/set-aside/NAICS candidates

Samples rows

Runs full EDA

Sends EDA to OpenAI

Displays a natural-language AI summary explaining:
✔ what the dataset represents
✔ which columns are important
✔ inferred meanings
✔ potential issues
✔ how the AI interprets the sheet

Natural-Language Processing & Querying

Users type instructions such as:

Give me SDVOSB solicitations posted between 2024-02-01 and 2024-02-15.
Return only NoticeId, Title, Type, PostedDate.


The AI generates a structured JSON plan defining:

Which columns to use

What filters to apply

What rows to keep

Which columns to include in output

How to structure the final sheets

And Python executes it safely and reliably.

Custom Excel & CSV Export

After filtering, the platform generates:

A cleaned Excel file (.xlsx)

A filtered CSV file

With custom sheet names and columns, based on the AI plan

Modern UI / UX

Built with a modern interface:

Dark dashboard theme

Multi-page UX (Welcome → Document Assistant → AI Writer)

Collapsible EDA section

AI explanations shown clearly

Smooth workflow:
Upload → AI Understanding → Prompt → Plan → Output

AI Writer / Conversation (Extra Module)

Includes a second workspace for:

Writing proposals

Summaries

Drafting emails

Brainstorming

General GPT interaction
(No dataset required)

Tech Stack

Python 3.10+

Streamlit (UI)

OpenAI GPT-4.1-mini (reasoning engine)

Pandas (data processing)

python-dotenv (local secrets)

Installation

Clone this repo:

git clone https://github.com/Dteebaba/Analytics-Agent
cd Analytics-Agent


Create a virtual environment:

python -m venv .venv
source .venv/bin/activate       # Linux/Mac
.\.venv\Scripts\activate        # Windows


Install dependencies:

pip install -r requirements.txt


Add your OpenAI API key to a .env file:

OPENAI_API_KEY="your key here"

Running Locally
streamlit run app.py


Then open:

http://localhost:8501

Deploying on Streamlit Cloud

Push your repo to GitHub

Go to https://share.streamlit.io

Click New App

Select your repo

Choose branch: main

Select file: app.py

Add your secret under Settings → Secrets:

OPENAI_API_KEY="your key"


Your app becomes publicly available under a URL like:

https://analytics-agent.streamlit.app

Repository Structure
Analytics-Agent/
│
├── app.py                # Main Streamlit application
├── data_engine.py        # EDA functions and dataset processing
├── llm_agent.py          # GPT logic: dataset summary + plan creation
├── requirements.txt      # Dependencies
├── .gitignore            # Ignore venv, .env, cache, etc.
└── README.md             # You're reading it :)

Example Prompts (for users)
Find solicitations between 2024-02-01 and 2024-02-10.
Return only NoticeId, Title, Type, PostedDate.

Filter SDVOSB opportunities containing "generator".

Give me all NAICS 541512 opportunities posted last week.

Create a summary grouped by NAICS and export as two sheets:
Filtered and Summary.

Contributing

Pull requests are welcome for:

More EDA enhancements

Additional AI modes

Visualization modules

Export templates

License

MIT License (or whatever you selected on GitHub).

Author

Developed by Dteebaba
AI-assisted data analytics and automation platform.