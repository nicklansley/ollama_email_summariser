# Ollama Email Summariser for Python



# Email Summariser

The Email Summariser is a Python script designed to automatically retrieve, process, categorize, and summarize emails using AI models. It leverages Gmail for email fetching and `ollama` for AI-powered categorization and summarization.

## Features

- Connects to Gmail to retrieve emails from the inbox.
- Uses AI models to categorize and summarize emails based on predefined categories.
- Supports summarization of both plain text and HTML emails.
- Generates a summarized email, grouping messages by categories.
- Automatically sends a summary email to the configured Gmail account.

## Prerequisites
- Ollama server application is installed from ollama.com
- The wanted model(s) are downloaded using the command below. (see the list at https://ollama.com/search - go for a model no larger than 7B unless you have a superfast GPU/neural processor)<pre>ollama pull model-name</pre>
- Python 3.x
- A Gmail account with email access enabled.
- `.env` file with the following environment variables:
    - `GMAIL_USERNAME`: Your Gmail address.
    - `GMAIL_PASSWORD`: Your Gmail password or app-specific password.
    - `CATEGORISING_AI_MODEL`: AI model identifier for categorizing emails (default: `llama3.1:latest`).
    - `SUMMARISING_AI_MODEL`: AI model identifier for summarizing emails (default: `llama3.1:latest`).
    - `INDIVIDUAL_EMAIL_SUMMARIES`: Set to "YES" if you want individual email summaries in the output.
    - `NEWSREADER_SCRIPT`: Set to "YES" to enable newsreader script formatting.
    - `NUM_CTX`: Number of context tokens for the AI model.
    - `HOURS_TO_FETCH`: Number of past hours to fetch emails.
    - `IGNORE_SENDERS`: A comma-separated list of emails to ignore during fetching (include the account's own email address!)

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/email-summariser.git
   cd email-summariser
   ```

2. **Create a virtual environment and activate it:**

   ```bash
   python3 -m venv env
   source env/bin/activate  # On Windows use `env\Scripts\activate`
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

4. **Set up your environment variables by creating a `.env` file based on the prerequisites.**

## Usage

Run the script using:

```bash
python your_script_name.py
```

The script will start fetching the emails, process them, and send a summarized email to your account.

## Contributing

Feel free to submit issues or pull requests if you find any bugs or have enhancements that could improve the application.

## License

This project is licensed under the MIT License. See the `LICENSE` file for more details.