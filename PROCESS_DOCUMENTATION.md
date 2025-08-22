# Step-by-Step Process Documentation

## 1. Chat Message Processing
### When a user sends a message:
1. User sends message through the web interface
2. Request arrives at `/send_message` endpoint
3. System processes the message in following steps:
   - Checks if the message matches any common questions
   - Looks for cached response (if exists and not expired)
   - If no cache hit, prepares prompt for Gemini AI:
     * Includes company information
     * Adds context from imsolutions_content.json
     * Formats prompt for concise response
4. Gemini AI generates response
5. Response is:
   - Cleaned (removes asterisks)
   - Limited to 6 lines
   - Cached for future use
   - Sent back to user

## 2. Appointment Management
### Scheduling an Appointment:
1. User submits appointment request to `/schedule_appointment`
2. System receives:
   - Title
   - Time
   - Optional notes
3. Validation process:
   - Checks time slot availability
   - Verifies format of inputs
4. If valid:
   - Creates calendar event
   - Stores in appointments.csv
   - Sends confirmation
5. If invalid:
   - Returns error message
   - Suggests alternative times

### Viewing Appointments:
1. Request to `/get_appointments`
2. System:
   - Reads appointments.csv
   - Formats appointment data
   - Returns list to user

### Canceling Appointments:
1. Request to `/cancel_appointment`
2. System:
   - Locates appointment
   - Removes from storage
   - Updates calendar
   - Sends cancellation confirmation

## 3. Voice Call Handling
### Incoming Call Process:
1. Call received at Twilio number
2. Twilio forwards to `/voice` endpoint
3. System:
   - Greets caller
   - Initiates voice gathering
   - Starts recording

### Voice Input Processing:
1. Voice input received at `/handle-voice-input`
2. System:
   - Converts speech to text
   - Processes text through Gemini AI
   - Converts response to speech
   - Plays response to caller

### Call Completion:
1. Call ends, triggers `/call-completed`
2. System:
   - Generates call summary
   - Saves to Google Sheets:
     * Timestamp
     * Call SID
     * Phone number
     * Duration
     * Summary
   - Updates local cache

## 4. Data Management
### Google Sheets Integration:
1. Authentication process:
   - Checks for existing token (token.pickle)
   - If expired, refreshes token
   - If no token, initiates OAuth2 flow
2. Data writing:
   - Prepares data in correct format
   - Appends to specified range
   - Verifies write success

### Cache Management:
1. Response caching:
   - Stores response with timestamp
   - Sets 1-hour expiry
   - Checks cache before API calls
2. Cache cleanup:
   - Removes expired entries
   - Maintains memory efficiency

## 5. Error Handling Process
1. Error Detection:
   - Try-catch blocks around critical operations
   - Input validation
   - API response checking

2. Error Response:
   - Logs error details
   - Generates user-friendly message
   - Falls back to default responses
   - Maintains service continuity

3. Recovery Process:
   - Automatic retry for transient failures
   - Service degradation if needed
   - Admin notification for critical errors

## 6. Security Processes
1. Authentication:
   - OAuth2 for Google services
   - Twilio authentication
   - API key validation

2. Data Protection:
   - Environment variable usage
   - Credential encryption
   - Secure token storage

3. Access Control:
   - Rate limiting
   - Request validation
   - Input sanitization

## 7. Maintenance Processes
### Regular Maintenance:
1. Cache Management:
   - Clear expired cache entries
   - Optimize cache size
   - Update cache rules

2. Token Management:
   - Monitor token expiration
   - Automatic token refresh
   - Backup token storage

3. Error Log Review:
   - Daily log analysis
   - Pattern identification
   - Performance optimization

4. API Quota Management:
   - Monitor usage rates
   - Implement throttling
   - Optimize API calls

### Emergency Maintenance:
1. Issue Detection:
   - Automated monitoring
   - Error rate tracking
   - Performance metrics

2. Response Protocol:
   - Service degradation if needed
   - Backup system activation
   - User notification

3. Recovery Steps:
   - Issue resolution
   - System verification
   - Service restoration

## 8. Deployment Process
1. Pre-deployment:
   - Code verification
   - Environment variable check
   - Dependency validation

2. Deployment:
   - Vercel configuration
   - Static file setup
   - Environment setup

3. Post-deployment:
   - Service verification
   - Integration testing
   - Performance monitoring

