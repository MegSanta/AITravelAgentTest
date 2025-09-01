import openai
import os
from dotenv import load_dotenv
import requests
import json
from datetime import datetime


# Load environment variables from .env file
load_dotenv()

# Set API keys from the environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")
flight_api_key = os.getenv("TRAVEL_API_KEY")

url = "https://api.flightapi.io/roundtrip"
# Set the parameters for the search (e.g., from, to, date, etc.)

def get_flight_data(url):
    # Send the GET request
    response = requests.get(url)
    # Check if the response was successful (status code 200)
    if response.status_code == 200:
        # Parse the response as JSON
        data = response.json()
        #print(json.dumps(data, indent=4)) #DEBUG
        data = parse_flights(data)  # Format the data using the helper function
        #print(json.dumps(formatted_flight_data, indent=4)) #DEBUG
    else:
        # Print error message if the request failed
        print(f"Error: {response.status_code} - {response.text}")
        data = ''
    return data

def chat_with_gpt(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # Model you want to use
        messages=[{"role": "user", "content": prompt}]
    )
    return response['choices'][0]['message']['content']

def parse_flights(data):
    # Build lookup tables
    legs_lookup = {leg["id"]: leg for leg in data.get("legs", [])}
    places_lookup = {p["id"]: p for p in data.get("places", [])}
    carriers_lookup = {c["id"]: c for c in data.get("carriers", [])}
    segments_lookup = {s["id"]: s for s in data.get("segments", [])}

    flights = []

    for itin in data.get("itineraries", []):
        price = itin["pricing_options"][0]["price"]["amount"]

        if len(itin["leg_ids"]) != 2:
            continue  # only handle round trips

        outbound_leg = legs_lookup[itin["leg_ids"][0]]
        return_leg = legs_lookup[itin["leg_ids"][1]]

        def format_leg(leg):
            origin = places_lookup[leg["origin_place_id"]]["display_code"]
            dest = places_lookup[leg["destination_place_id"]]["display_code"]

            # Expand segment info
            segments = []
            for sid in leg["segment_ids"]:
                seg = segments_lookup[sid]
                carrier = carriers_lookup[seg["marketing_carrier_id"]]
                segments.append({
                    "segment_id": sid,
                    "airline": carrier["name"],
                    "airline_code": carrier["display_code"],
                    "flight_number": seg["marketing_flight_number"],
                    "origin": places_lookup[seg["origin_place_id"]]["display_code"],
                    "destination": places_lookup[seg["destination_place_id"]]["display_code"],
                    "departure_time": datetime.fromisoformat(seg["departure"]),
                    "arrival_time": datetime.fromisoformat(seg["arrival"]),
                    "duration": seg["duration"],
                })

            return {
                "origin": origin,
                "destination": dest,
                "departure_time": datetime.fromisoformat(leg["departure"]),
                "arrival_time": datetime.fromisoformat(leg["arrival"]),
                "duration": leg["duration"],
                "segments": segments,
                "is_direct": len(segments) == 1
            }

        flights.append({
            "price_usd": price,
            "outbound": format_leg(outbound_leg),
            "return": format_leg(return_leg),
        })

    return flights

def format_flight_for_humans(flight):
    """
    Takes one parsed flight dictionary from parse_flights() and returns
    a ChatGPT-friendly string with segment-level details.
    """
    
    def format_leg(leg, leg_name="Outbound"):
        lines = [f"{leg_name} Flight:"]
        lines.append(f"- From {leg['origin']} to {leg['destination']}")
        lines.append(f"- Departure: {leg['departure_time'].strftime('%Y-%m-%d %I:%M %p')}")
        lines.append(f"- Arrival: {leg['arrival_time'].strftime('%Y-%m-%d %I:%M %p')}")
        lines.append(f"- Duration: {leg['duration']} minutes")
        lines.append(f"- Direct Flight: {'Yes' if leg['is_direct'] else 'No'}")
        lines.append("- Segments:")
        for seg in leg['segments']:
            lines.append(f"  - {seg['airline']} {seg['airline_code']}{seg['flight_number']}: "
                         f"{seg['origin']} → {seg['destination']}, "
                         f"Dep: {seg['departure_time'].strftime('%I:%M %p')}, "
                         f"Arr: {seg['arrival_time'].strftime('%I:%M %p')}, "
                         f"Duration: {seg['duration']} min")
        return "\n".join(lines)

    output_lines = [f"Price: ${flight['price_usd']:.2f}"]
    output_lines.append(format_leg(flight['outbound'], "Outbound"))
    output_lines.append(format_leg(flight['return'], "Return"))
    
    return "\n\n".join(output_lines)

def format_flights(flights):
    return [format_flight_for_humans(flight) for flight in flights]


def get_cheapest_flight(flights):
        if not flights:
            return None  # Return None if the list is empty

        cheapest_flight = min(flights, key=lambda x: x['price_usd'])
        return cheapest_flight


def simplify_parsed_flights(flights, max_results=10):
    """
    Take the output of parse_flights() and return a trimmed-down version
    that is short enough for GPT prompts.
    """
    simplified = []

    for f in flights[:max_results]:
        def format_leg(leg):
            return {
                "route": f"{leg['origin']} → {leg['destination']}",
                "departure": leg["departure_time"].strftime("%Y-%m-%d %H:%M"),
                "arrival": leg["arrival_time"].strftime("%Y-%m-%d %H:%M"),
                "segments": [
                    f"{seg['airline_code']}{seg['flight_number']} "
                    f"{seg['origin']}→{seg['destination']} "
                    f"({seg['departure_time'].strftime('%H:%M')}→{seg['arrival_time'].strftime('%H:%M')})"
                    for seg in leg["segments"]
                ]
            }

        simplified.append({
            "price_usd": f["price_usd"],
            "outbound": format_leg(f["outbound"]),
            "return": format_leg(f["return"]),
        })

    return simplified


def main():
    year = datetime.now().year
    user_request = input()
    response = chat_with_gpt(f"""
    Please respond with the following formatted information based on this user's request: {user_request}. 
    - "From" and "To" should be 3-letter airport codes (IATA format).
    - If the user provides city names instead of airport codes, choose the closest airport based on the city.
    - Dates should be in "yyyy-mm-dd" format.
    - If the user does not provide a year, assume it is the current year, {year}.
    - The final output should be in this format:
    from/to/arrival_date/departure_date
    """)
    #print("Response from ChatGPT:", response)
    flight_url = f'{url}/{flight_api_key}/{response}/1/0/1/Economy/USD'
    print("Flight URL:", flight_url)  #DEBUG

    #check chat response before wasting api call
    continue_decision = input("Do you want to continue with this url? (yes/no): ").strip().lower()
    if continue_decision != 'yes':
        return

    # Get flight data from the API
    flight_data = get_flight_data(flight_url)

    # Load test data
    # Example: read your JSON file
    # with open("flights2.json", "r", encoding="utf-8") as f:
    #     flight_data = json.load(f)
    #     flight_data = parse_flights(flight_data)  # Format the data using the helper function

    simplified_flight_data = simplify_parsed_flights(flight_data)

    #print("flight data returned and processed for chat:/n", simplified_flight_data)

    readable_flight_data = format_flights(flight_data)
    #print(readable_flight_data)  #DEBUG
    
    travel_plan_response = chat_with_gpt(f"""
    Please provide a travel plan based on this request: {user_request}.

    User request may contain preferences such as:
    - Cheapest option
    - Avoiding morning flights
    - Avoiding long layovers
    - Preferred airlines, etc.

    From the following flight data: {simplified_flight_data}, choose ONLY ONE departure and return flight that strictly meets the user's request. 

    Rules:
    1. If the user asks for 'cheapest', pick the flight with the lowest price in USD.
    2. If the user specifies time constraints (e.g., "no morning flights"), exclude flights violating that constraint.
    3. If multiple flights meet the criteria, pick the one with the earliest departure.
    4. Return exactly one itinerary.

    Format the response like this:
    - Price in USD
    - Outbound flight:
    - departure airport code, arrival airport code
    - departure time, arrival time in 12-hour format with AM/PM
    - segment_ids
    - airline name + flight number for each segment
    - Return flight:
    - departure airport code, arrival airport code
    - departure time, arrival time
    - segment_ids
    - airline name + flight number for each segment
    """)
    
    print("\nTravel Plan Response from ChatGPT:\n", travel_plan_response)

    print("\nCheapest flight by parsing:\n", get_cheapest_flight(simplified_flight_data))  #DEBUG
        


main()

