"""
Everything the bot says, in English and Spanish.

All speech is generated live by Plivo's text-to-speech (the <Speak> element)
with the voices below, so you can change any sentence here without touching
the call flow.
"""

# Plivo <Speak> voice settings for each language.
VOICES = {
    "en": {"voice": "WOMAN", "language": "en-US"},
    "es": {"voice": "WOMAN", "language": "es-ES"},
}

LANGUAGE_NAMES = {"en": "English", "es": "Spanish"}

PROMPTS = {
    "en": {
        # Before the caller picks a language, the bot speaks English.
        "welcome": "Welcome to InspireWorks.",
        "otp_ask": "To verify your identity, please enter your 4 digit passcode.",
        "otp_wrong": "Sorry, that passcode is incorrect. Please try again.",
        "otp_too_short": "Sorry, the passcode has 4 digits. Please try again.",
        "otp_ok": "Thank you. You are verified.",
        # Level 1 is spoken in both languages: "For English, press 1. Para español, presione 2."
        "language_ask": "For English, press 1.",
        # Level 2
        "menu_ask": "Press 1 to hear a short audio message. "
                    "Press 2 to talk to a live associate. "
                    "Press 9 to change the language.",
        "audio_intro": "Here is your short audio message.",
        "connecting": "Connecting you to an associate. Please hold.",
        "associate_unavailable": "Sorry, the associate is not available right now.",
        # Invalid input, silence, goodbye
        "invalid": "Sorry, that is not a valid option.",
        "no_input": "Sorry, I did not hear any key press.",
        "goodbye": "Thank you for calling InspireWorks. Goodbye!",
        "silent_goodbye": "We did not hear from you, so we will end the call now. Goodbye!",
    },
    "es": {
        "language_ask": "Para español, presione 2.",
        "menu_ask": "Presione 1 para escuchar un breve mensaje de audio. "
                    "Presione 2 para hablar con un asociado. "
                    "Presione 9 para cambiar el idioma.",
        "audio_intro": "Aquí está su breve mensaje de audio.",
        "connecting": "Le estamos conectando con un asociado. Por favor, espere.",
        "associate_unavailable": "Lo sentimos, el asociado no está disponible en este momento.",
        "invalid": "Lo sentimos, esa opción no es válida.",
        "no_input": "Lo sentimos, no escuchamos ninguna tecla.",
        "goodbye": "Gracias por llamar a InspireWorks. ¡Adiós!",
        "silent_goodbye": "No hemos recibido respuesta, así que terminaremos la llamada. ¡Adiós!",
    },
}
