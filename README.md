# Flask Chatbot with ChatGPT Integration

A chatbot implementation using Flask and Python, powered by OpenAI's ChatGPT API.

## Features

- Web-based chat interface
- Real-time message exchange
- Powered by OpenAI's GPT-3.5 Turbo
- Modern and responsive design

## Setup Instructions

1. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install the required packages:
```bash
pip install -r requirements.txt
```

3. Set up your OpenAI API key:
   - Create a `.env` file in the project root
   - Add your OpenAI API key: `OPENAI_API_KEY=your_api_key_here`
   - You can get an API key from [OpenAI's platform](https://platform.openai.com/api-keys)

4. Run the application:
```bash
python app.py
```

5. Open your web browser and navigate to:
```
http://localhost:5000
```

## Usage

- Type your message in the input box
- Press Enter or click the Send button to send your message
- The chatbot will respond using ChatGPT's AI capabilities

## Customization

You can customize the chatbot's behavior by modifying the system message and parameters in the `get_chatgpt_response` function in `app.py`:
- Change the model (e.g., to "gpt-4")
- Adjust the temperature (0.0 to 1.0)
- Modify the max_tokens
- Update the system message 