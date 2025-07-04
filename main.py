import streamlit as st
import uuid
import datetime
import pytz
import pandas as pd
from streamlit_searchbox import st_searchbox # type: ignore
from utils.pages import set_page_config
from utils.predicthq import (
    get_api_key,
    get_predicthq_client,
    fetch_events,
    ATTENDED_CATEGORIES,
    NON_ATTENDED_CATEGORIES,
    UNSCHEDULED_CATEGORIES,
)
from utils.google import places_autocomplete, get_place_details
from utils.map import show_map
from utils.metrics import show_metrics
from dateutil.parser import parse as parse_date


def main():
    set_page_config("Location Insights")

    st.session_state.google_session_token = uuid.uuid4().hex

    if get_api_key() is not None:
        show_address_lookup()
    else:
        st.warning("Please set a PredictHQ API Token.", icon="⚠️")


def lookup_address(text):
    if len(text) > 0:
        results = places_autocomplete(text, session_token=st.session_state.google_session_token)

        return [
            (
                str(result["description"]),
                result["place_id"],
            )
            for result in results
        ]
    else:
        return []


def show_address_lookup():
    st.markdown(
        """
        <div style='text-align: center;'>
            <div style='margin-bottom: 20px;'>
            <h1>Location Insights</h1>
            <p>Discover nearby events that will fill your tables and boost your revenue.</p>
           
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.title(st.secrets["title"])

    place_id = st_searchbox(
        lookup_address,
        # label="Discover nearby events that will fill your tables and boost your revenue :",
        placeholder="e.g. 123 Main St, Anytown, USA",
        clear_on_submit=True,
        key="address",
    )

    if place_id is not None:
        show_location_insights(place_id)


@st.cache_data
def show_location_insights(place_id):
    # Lookup place details
    place_details = get_place_details(
        place_id=place_id,
        session_token=st.session_state.google_session_token,
    )

    name = place_details["result"]["name"]
    lat = place_details["result"]["geometry"]["location"]["lat"]
    lon = place_details["result"]["geometry"]["location"]["lng"]
    tz = "UTC"

    date_from = datetime.datetime.now().date()
    date_to = date_from + datetime.timedelta(days=90)

    categories = ATTENDED_CATEGORIES
    suggested_radius_industry = st.secrets["suggested_radius_industry"] if "suggested_radius_industry" in st.secrets else "accommodation"

    radius, radius_unit = fetch_suggested_radius(lat, lon, radius_unit="mi", industry=suggested_radius_industry)

    # st.write(place_details)
    # st.header(name)
    st.header(f"Over the next 90 days in {name}, you could be missing out on:")

    # Display metrics
    show_metrics(
        lat=lat,
        lon=lon,
        radius=radius,
        radius_unit=radius_unit,
        date_from=date_from,
        date_to=date_to,
        suggested_radius={"radius": radius, "radius_unit": radius_unit},
        tz=tz
    )

    # Fetch events
    events = fetch_events(
        lat,
        lon,
        radius=radius,
        date_from=date_from,
        date_to=date_to,
        tz=tz,
        categories=categories,
        radius_unit=radius_unit,
    )

    # Show map and convert radius miles to meters (the map only supports meters)
    show_map(
        lat=lat,
        lon=lon,
        radius_meters=calc_meters(radius, radius_unit),
        events=events,
    )

    show_events_list(events)


@st.cache_data
def fetch_suggested_radius(lat, lon, radius_unit="mi", industry="parking"):
    phq = get_predicthq_client()
    suggested_radius = phq.radius.search(location__origin=f"{lat},{lon}", radius_unit=radius_unit, industry=industry)

    return suggested_radius.radius, suggested_radius.radius_unit


def calc_meters(value, unit):
    if unit == "mi":
        return value * 1609
    if unit == "ft":
        return value * 0.3048
    elif unit == "km":
        return value * 1000
    else:
        return value


def show_events_list(events):
    """
    We're also converting start/end times to local timezone here from UTC.
    """
    results = []

    for event in events["results"]:
        venue = next(filter(lambda entity: entity["type"] == "venue", event["entities"]), None)

        row = {
            # "id": event["id"],
            "Event Title": event["title"],
            "PHQ Attendance": event["phq_attendance"] if event["phq_attendance"] else 0,
            "Category": event["category"],
            "Start Date (local tz)": parse_date(event["start"])
            .astimezone(pytz.timezone(event["timezone"]))
            .strftime("%d-%b-%Y %H:%M"),
            "End Date (local tz)": parse_date(event["end"])
            .astimezone(pytz.timezone(event["timezone"]))
            .strftime("%d-%b-%Y %H:%M"),
            "Predicted End Date (local tz)": parse_date(event["predicted_end"])
            .astimezone(pytz.timezone(event["timezone"]))
            .strftime("%d-%b-%Y %H:%M")
            if "predicted_end" in event and event["predicted_end"] is not None
            else "",
            "Venue Name": venue["name"] if venue else "",
            "Venue Address": venue["formatted_address"] if venue else "",
            "Placekey": event["geo"]["placekey"] if "geo" in event and "placekey" in event["geo"] else "",
            "Predicted Event Spend": f"${event['predicted_event_spend']:,.0f}"
            if "predicted_event_spend" in event and event["predicted_event_spend"] is not None
            else "",
            "Predicted Event Spend (Hospitality)": f"${event['predicted_event_spend_industries']['hospitality']:,.0f}"
            if "predicted_event_spend_industries" in event
            and event["predicted_event_spend_industries"]["hospitality"] is not None
            else "",
        }

        results.append(row)

    events_df = pd.DataFrame(results)
    st.dataframe(events_df)


if __name__ == "__main__":
    main()