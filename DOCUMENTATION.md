# IM Solutions Chatbot Documentation

## Project Overview
This is a sophisticated chatbot application built with Flask that integrates various services including Google's Gemini AI, Twilio for voice calls, and Google Sheets for data storage. The chatbot serves as a customer service representative for IM Solutions, handling both text and voice interactions.

## Technical Stack
- **Backend Framework**: Flask (Python)
- **AI Model**: Google Gemini 2.0 Flash
- **Voice Services**: Twilio
- **Data Storage**: Google Sheets
- **Additional Technologies**: 
  - BeautifulSoup for web scraping
  - iCalendar for calendar management
  - OAuth2 for Google services authentication

## Key Features
1. **Intelligent Chat Responses**
   - Integration with Google's Gemini AI
   - Cached responses for improved performance
   - Pre-defined responses for common questions
   - Context-aware conversations

2. **Voice Call Handling**
   - Twilio integration for voice calls
   - Voice-to-text processing
   - Automated call responses
   - Call summary logging

3. **Appointment Management**
   - Schedule appointments
   - View appointments
   - Cancel appointments
   - Calendar integration

4. **Data Management**
   - Google Sheets integration for call logging
   - Local caching system
   - Persistent storage for appointments
   - Error logging and monitoring

## API Endpoints

### Chat Endpoints
- `GET /` - Main chat interface
- `POST /send_message` - Process chat messages

### Appointment Endpoints
- `POST /schedule_appointment` - Create new appointments
- `GET /get_appointments` - Retrieve appointments
- `POST /cancel_appointment` - Cancel existing appointments

### Voice Call Endpoints
- `POST /voice` - Handle incoming voice calls
- `POST /handle-voice-input` - Process voice inputs
- `POST /call-completed` - Handle call completion
- `POST /initiate-call` - Start outbound calls

## Configuration
The application requires several environment variables:
- `GEMINI_API_KEY` - Google Gemini AI API key
- `TWILIO_ACCOUNT_SID` - Twilio account identifier
- `TWILIO_AUTH_TOKEN` - Twilio authentication token
- `TWILIO_PHONE_NUMBER` - Twilio phone number

## Data Storage
1. **Google Sheets**
   - Used for storing call summaries
   - Spreadsheet ID: Configured in environment
   - Range: 'Calls!A:E'

2. **Local Storage**
   - `token.pickle` - Google OAuth credentials
   - `imsolutions_content.json` - Company information
   - `appointments.csv` - Appointment data

## Caching System
- Response caching with 1-hour expiry
- In-memory cache for frequently asked questions
- Cached Google Sheets authentication

## Error Handling
- Comprehensive logging system
- Fallback responses for API failures
- Error tracking and reporting

## Security Features
- OAuth2 authentication for Google services
- Secure credential management
- Environment variable protection

## Dependencies
Key dependencies are listed in `requirements.txt`:
- Flask
- google-generativeai
- python-dotenv
- requests
- beautifulsoup4
- pytz
- icalendar
- twilio
- google-auth-oauthlib
- google-api-python-client

## Deployment
The application is configured for deployment with:
- Vercel configuration (vercel.json)
- Environment variable management
- Static file serving

## Maintenance
- Regular cache clearing
- Token refresh handling
- Error log monitoring
- API quota management

## Best Practices
1. **Rate Limiting**
   - Implemented for API calls
   - Cache utilization
   - Request throttling

2. **Error Recovery**
   - Graceful degradation
   - Fallback responses
   - Error logging

3. **Data Management**
   - Regular backups
   - Data validation
   - Secure storage

## Support and Contact
For technical support or inquiries, contact the development team through the corporate office contacts specified in the configuration.

---
Last Updated: [Current Date]
Version: 1.0 