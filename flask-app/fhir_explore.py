# fhir_explore.py
#
# This script talks to a free, public "practice" healthcare server on the
# internet. That server speaks a language called FHIR, which is the standard
# way hospitals and clinics share data like patients and referral requests.
#
# The script does two things:
#   1. Asks the server for 5 patients and prints their names and ID numbers.
#   2. Asks the server for 5 "service requests" (think: referral/order forms)
#      and prints their status, which patient they belong to, and the reason.
#
# If the server is unreachable or misbehaves, the script prints a friendly
# message instead of crashing with scary technical errors.

# "import" means: bring in a toolbox of ready-made code so we can use it.
# "requests" is a popular toolbox for fetching things from the internet,
# similar to how a web browser fetches a web page.
import requests

# This is the web address of the public practice FHIR server.
# "baseR4" means it speaks version R4 of the FHIR standard.
BASE_URL = "https://hapi.fhir.org/baseR4"

# How many seconds we are willing to wait for the server to answer
# before giving up. Without this, a slow server could make us wait forever.
TIMEOUT_SECONDS = 15


def fetch_bundle(resource_type, count):
    """Ask the server for a list of records and hand back the response.

    'resource_type' is the kind of record we want (e.g. "Patient").
    'count' is how many records we want.
    """
    # Build the full web address. For example:
    # https://hapi.fhir.org/baseR4/Patient?_count=5&_sort=-_lastUpdated
    # The "?_count=5" part tells the server "only send me 5".
    # The "_sort=-_lastUpdated" part asks for the most recently updated
    # records first. This also nudges this particular public server to
    # actually include the records in its answer (without it, the server
    # sometimes replies with an empty page).
    url = f"{BASE_URL}/{resource_type}?_count={count}&_sort=-_lastUpdated"

    # Actually contact the server and wait for its answer.
    response = requests.get(url, timeout=TIMEOUT_SECONDS)

    # If the server answered with an error code (like "500 Server Error"),
    # this line raises an alarm that our error handling below will catch.
    response.raise_for_status()

    # The server sends data in a text format called JSON.
    # ".json()" converts that text into a structure Python can work with,
    # like turning a printed form into an organized filing cabinet.
    return response.json()


def print_patients():
    """Fetch 5 patients and print each one's name and ID."""
    # A heading so the output is easy to read.
    print("=== 5 Patients from the public FHIR server ===")

    # Ask the server for 5 Patient records.
    bundle = fetch_bundle("Patient", 5)

    # FHIR wraps lists of records in a package called a "bundle".
    # The actual records live under the key "entry".
    # ".get('entry', [])" means: give me the entries, or an empty list
    # if there are none (so we don't crash on an empty answer).
    entries = bundle.get("entry", [])

    # If the list is empty, say so and stop this section.
    if not entries:
        print("The server returned no patients.")
        return

    # Go through the records one at a time.
    for entry in entries:
        # Each entry has a "resource" inside it -- the patient record itself.
        patient = entry.get("resource", {})

        # Every record has an "id" -- its unique number on the server.
        patient_id = patient.get("id", "(no ID)")

        # Names in FHIR are stored as a list, because a person can have
        # several names (legal name, maiden name, nickname...).
        # We take the first name entry if there is one.
        names = patient.get("name", [])
        if names:
            first_name_entry = names[0]

            # A name is split into pieces:
            # "given" = first/middle names (a list), "family" = last name.
            given_names = " ".join(first_name_entry.get("given", []))
            family_name = first_name_entry.get("family", "")

            # Glue the pieces together, and tidy up extra spaces.
            full_name = f"{given_names} {family_name}".strip()

            # Some records have a name section but no actual text in it.
            if not full_name:
                full_name = "(name not recorded)"
        else:
            full_name = "(name not recorded)"

        # Print one line per patient: their name and their ID.
        print(f"  Name: {full_name}  |  ID: {patient_id}")


def print_service_requests():
    """Fetch 5 service requests and print status, patient, and reason."""
    # A heading for this section of the output.
    print()
    print("=== 5 ServiceRequests (referral/order forms) ===")

    # Ask the server for 5 ServiceRequest records.
    bundle = fetch_bundle("ServiceRequest", 5)

    # Pull out the list of records, just like we did for patients.
    entries = bundle.get("entry", [])

    # If the list is empty, say so and stop this section.
    if not entries:
        print("The server returned no service requests.")
        return

    # Go through the records one at a time.
    for entry in entries:
        # The actual service-request record.
        request_record = entry.get("resource", {})

        # "status" tells us where the request is in its life:
        # e.g. "active", "completed", "draft".
        status = request_record.get("status", "(no status)")

        # "subject" points to the patient this request is about.
        # It usually looks like "Patient/12345" -- a reference, like
        # writing someone's file number on a form instead of their whole file.
        subject = request_record.get("subject", {})
        patient_reference = subject.get("reference", "(no patient reference)")

        # The reason can be stored in two different ways in FHIR:
        # as written-out text/codes ("reasonCode") or as a pointer to
        # another record ("reasonReference"). We check both.
        reason = "(no reason recorded)"

        # First way: "reasonCode" -- a list of coded/text reasons.
        reason_codes = request_record.get("reasonCode", [])
        if reason_codes:
            # Prefer the human-readable "text" if it exists.
            text = reason_codes[0].get("text")
            if text:
                reason = text
            else:
                # Otherwise, look inside the coding for a display label.
                codings = reason_codes[0].get("coding", [])
                if codings and codings[0].get("display"):
                    reason = codings[0]["display"]
        else:
            # Second way: "reasonReference" -- a pointer to another record
            # (for example, a Condition record describing a diagnosis).
            reason_refs = request_record.get("reasonReference", [])
            if reason_refs:
                # Use the pointer's display name or its reference text.
                reason = reason_refs[0].get("display") or reason_refs[0].get(
                    "reference", reason
                )

        # Print one line per request with the three facts we collected.
        print(
            f"  Status: {status}  |  Patient: {patient_reference}"
            f"  |  Reason: {reason}"
        )


def main():
    """Run both sections, and handle problems gracefully."""
    # "try" means: attempt the following steps, but be ready to catch
    # problems instead of crashing.
    try:
        print_patients()
        print_service_requests()

    # This catches "the server took too long to answer".
    except requests.exceptions.Timeout:
        print(
            "The FHIR server took too long to respond. "
            "It may be busy -- please try again in a moment."
        )

    # This catches "we couldn't reach the server at all"
    # (no internet, server down, wrong address...).
    except requests.exceptions.ConnectionError:
        print(
            "Could not connect to the FHIR server. "
            "It may be down, or your internet connection may be offline."
        )

    # This catches "the server answered, but with an error"
    # (like a 500 Internal Server Error page).
    except requests.exceptions.HTTPError as error:
        print(f"The FHIR server returned an error: {error}")

    # This is a safety net for any other unexpected problem,
    # so the script always ends with a readable message.
    except Exception as error:
        print(f"Something unexpected went wrong: {error}")


# This line means: "only run main() when this file is executed directly"
# (as opposed to being borrowed by another script). It's a standard
# Python convention -- like a light switch that turns the script on.
if __name__ == "__main__":
    main()
