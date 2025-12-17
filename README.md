# 🚀 YouTube Comment Data Warehouse Project

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/optyj59/Dali_dataCrawling)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This project is a sophisticated data pipeline designed to crawl, process, and store YouTube video comments in a structured data warehouse. It provides dual crawling engines (high-speed `requests` and robust `Playwright`) and is built to handle temporal data using a hybrid SCD (Slowly Changing Dimensions) model.

## ✨ Features

- **Dual Crawling Engines**: Choose between a lightweight, high-speed `requests`-based engine or a robust, browser-based `Playwright` engine for data collection.
- **Intelligent Filtering**: Filters videos based on view and comment counts to optimize crawling resources.
- **Temporal Data Model (SCD Type 2)**: Tracks the history of comments and video metadata, preserving changes over time.
- **PII Masking**: Automatically detects and masks Personally Identifiable Information (PII) like email addresses and phone numbers in comments.
- **Parallel Processing**: Utilizes multiprocessing to significantly speed up the crawling of multiple videos.

## 🏗️ Architecture

The project follows a modular architecture designed for scalability and maintainability.

### Technology Stack

- **Crawling**: Python, Requests, Playwright
- **HTML Parsing**: Beautiful Soup (BS4)
- **Database**: PostgreSQL (designed for, but not directly integrated in this repository)
- **Orchestration**: Standard Python `multiprocessing`.

### Data Pipeline

1.  **Search**: Takes a user-provided keyword and searches YouTube for a list of candidate video IDs.
2.  **Filter**: Filters the candidate videos based on view and comment count thresholds.
3.  **Crawl**: For each filtered video, the chosen engine (`requests` or `Playwright`) scrapes all comments and their replies.
4.  **Store**: The collected data is saved to CSV files in the `output/raw/` directory, formatted and ready for ingestion into a database.

## 🏁 Getting Started

Follow these instructions to get a copy of the project up and running on your local machine.

### Prerequisites

- Python 3.8+
- pip (Python package installer)

The following Python libraries are required. You can install them using pip:

```sh
pip install beautifulsoup4
pip install playwright
pip install psycopg2-binary
pip install requests
```

Alternatively, you can create a `requirements.txt` file with the contents above and install them all at once:

```sh
pip install -r requirements.txt
```

Additionally, you'll need to install the browser binaries for Playwright:
```sh
playwright install
```

## 🚀 Usage

To start the crawling process, run `main.py` from the root directory:

```sh
python main.py
```

The script will guide you through a series of interactive prompts:

1.  **Enter a keyword**: The keyword to search for on YouTube (e.g., `파이썬 강좌`).
2.  **Select a crawler engine**: Choose between `requests` or `playwright`.
    -   `requests`: Faster, lighter, but potentially more fragile to YouTube UI changes.
    -   `playwright`: Slower, more robust, as it simulates a real user in a browser.

The script will then begin the crawling process, and the collected data will be saved as CSV files in the `output/raw/` directory.

## 🗃️ Database Schema

This project is designed to populate a data warehouse with a hybrid SCD model. The schema includes tables for keywords, videos, metadata history, and comments. For a detailed overview of the database structure, please see [database_schema.md](./database_schema.md).

## 🤝 Contributing

Contributions are what make the open-source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  Push to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a Pull Request

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
