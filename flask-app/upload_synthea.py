# upload_synthea.py
#
# Uploads 10 Synthea-generated patient bundles from the synthea_data folder
# to the public HAPI FHIR server, so you have your own known test patients.
#
# Each Synthea file is a FHIR "transaction bundle" -- a single package
# containing one Patient plus all their related records (encounters,
# conditions, medications, ...). We POST the whole bundle to the server's
# base URL; the server creates everything in one shot and assigns its own
# IDs. The server's answer tells us the new ID of every created record --
# we pick out the Patient's ID, print it, and save all IDs to
# my_patients.txt.
#
# THE PUBLIC SERVER HAS TWO QUIRKS we must work around:
#   1. It rejects "conditional references" (links that look like
#      "Practitioner?identifier=..."), which Synthea uses for doctors and
#      hospitals. We remove those links before uploading -- the patient's
#      clinical data is unaffected.
#   2. It rejects uploads that are too large (HTTP 413). Synthea bundles
#      include full clinical note documents encoded as text blobs, which
#      are most of the bulk. We drop those notes, and if a bundle is STILL
#      too big we trim the newest records from the end until it fits.
#
# NOTE ON RATE LIMITS: hapi.fhir.org is a free, shared, public test server.
# It does not publish an official rate limit, but it throttles or rejects
# heavy traffic (HTTP 429/503). We pause between uploads to be polite and
# retry once if throttled.

import json
import os
import sys
import time

import requests

BASE_URL = "https://hapi.fhir.org/baseR4"
DATA_DIR = "synthea_data"          # folder with the Synthea JSON bundles
OUTPUT_FILE = "my_patients.txt"    # where we save the new patient IDs
UPLOAD_LIMIT = 10                  # how many bundles to upload
DELAY_SECONDS = 3                  # polite pause between uploads
TIMEOUT_SECONDS = 120              # bundles are big; give the server time
MAX_BUNDLE_BYTES = 900_000         # stay under the server's size limit

# Resource types we drop entirely to shrink the upload. DocumentReference
# entries hold entire encoded clinical notes and are most of the file size.
DROP_RESOURCE_TYPES = {"DocumentReference"}

HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json",
}


def strip_conditional_references(obj):
    """Remove reference links the public server can't process.

    Synthea points at doctors/organizations with lookup-style references
    like {"reference": "Practitioner?identifier=..."}. This server rejects
    those, so we blank out the lookup part and keep only the display name.
    """
    if isinstance(obj, dict):
        ref = obj.get("reference")
        if isinstance(ref, str) and "?" in ref:
            del obj["reference"]  # keep "display" if present
        for value in obj.values():
            strip_conditional_references(value)
    elif isinstance(obj, list):
        for item in obj:
            strip_conditional_references(item)


def strip_dangling_urn_references(obj, kept_urns):
    """Remove links that point at records we removed from the bundle.

    Inside a bundle, records point at each other with temporary
    "urn:uuid:..." labels. If we removed a record (e.g. a clinical note),
    any leftover link to its label would make the server reject the whole
    upload -- so we delete those links.
    """
    if isinstance(obj, dict):
        ref = obj.get("reference")
        if isinstance(ref, str) and ref.startswith("urn:uuid:") and ref not in kept_urns:
            del obj["reference"]
        for value in obj.values():
            strip_dangling_urn_references(value, kept_urns)
    elif isinstance(obj, list):
        for item in obj:
            strip_dangling_urn_references(item, kept_urns)


def clean_bundle(bundle):
    """Prepare a Synthea bundle so the public server will accept it."""
    # 1. Drop the bulky clinical-note documents.
    bundle["entry"] = [
        e for e in bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") not in DROP_RESOURCE_TYPES
    ]

    # 2. Remove unsupported lookup-style references everywhere.
    strip_conditional_references(bundle)

    # 3. Remove "only create if it doesn't already exist" instructions
    # (ifNoneExist). This server responds to them with a hard error
    # (HTTP 412) when a matching record already exists, instead of
    # quietly reusing it. Removing the instruction does a plain create.
    for entry in bundle["entry"]:
        entry.get("request", {}).pop("ifNoneExist", None)

    # 4. Replace stand-alone Medication records with inline drug codes.
    # This public server refuses to create a Medication that duplicates
    # one it already has (HTTP 412), and common drugs are already there.
    # FHIR lets a prescription carry the drug code directly instead of
    # pointing at a separate Medication record -- so we do that.
    med_codes = {}  # temporary label -> the drug's code block
    for entry in bundle["entry"]:
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Medication" and resource.get("code"):
            med_codes[entry.get("fullUrl")] = resource["code"]

    # Remove the Medication records themselves...
    bundle["entry"] = [
        e for e in bundle["entry"]
        if e.get("resource", {}).get("resourceType") != "Medication"
    ]

    # ...and rewrite anything that pointed at them to carry the code.
    for entry in bundle["entry"]:
        resource = entry.get("resource", {})
        med_ref = resource.get("medicationReference", {}).get("reference")
        if med_ref in med_codes:
            del resource["medicationReference"]
            resource["medicationCodeableConcept"] = med_codes[med_ref]

    # 5. If still too large, trim records from the END of the bundle.
    # Synthea lists records in story order (Patient first, newest events
    # last), and later records only point backwards at earlier ones -- so
    # trimming the tail keeps the remaining records consistent.
    while len(json.dumps(bundle).encode()) > MAX_BUNDLE_BYTES and len(bundle["entry"]) > 1:
        bundle["entry"] = bundle["entry"][: max(1, int(len(bundle["entry"]) * 0.8))]

    # 6. Delete any links that still point at records we removed above
    # (e.g. audit-trail records pointing at the dropped clinical notes).
    kept_urns = {e.get("fullUrl") for e in bundle["entry"]}
    strip_dangling_urn_references(bundle, kept_urns)

    return bundle


def find_patient_id(response_bundle):
    """Pull the server-assigned Patient ID out of a transaction-response.

    Each entry in the response has a 'response.location' like:
        Patient/137275999/_history/1
    We find the Patient one and return the ID part ("137275999").
    """
    for entry in response_bundle.get("entry", []):
        location = entry.get("response", {}).get("location", "")
        if location.startswith("Patient/"):
            return location.split("/")[1]
    return None


def upload_bundle(path):
    """Clean and upload one bundle file. Returns the new Patient ID."""
    with open(path, "r", encoding="utf-8") as f:
        bundle = json.load(f)

    bundle = clean_bundle(bundle)

    response = requests.post(
        BASE_URL, json=bundle, headers=HEADERS, timeout=TIMEOUT_SECONDS
    )

    # 429/503 = throttled or overloaded. Wait and retry once.
    if response.status_code in (429, 503):
        print("    Server is rate-limiting us -- waiting 30s and retrying once...")
        time.sleep(30)
        response = requests.post(
            BASE_URL, json=bundle, headers=HEADERS, timeout=TIMEOUT_SECONDS
        )

    response.raise_for_status()
    return find_patient_id(response.json())


def main():
    print("WARNING: hapi.fhir.org is a free public test server.")
    print("It has no guaranteed uptime and throttles heavy traffic")
    print(f"(HTTP 429/503). Uploading {UPLOAD_LIMIT} bundles with a")
    print(f"{DELAY_SECONDS}-second pause between each to stay polite.")
    print("Note: data on the public server is periodically wiped, so your")
    print("test patients may not live there forever.")
    print()

    if not os.path.isdir(DATA_DIR):
        print(f"Folder '{DATA_DIR}' not found. Run this from the folder that")
        print("contains synthea_data.")
        sys.exit(1)

    files = sorted(
        f for f in os.listdir(DATA_DIR) if f.endswith(".json")
    )[:UPLOAD_LIMIT]

    if not files:
        print(f"No .json files found in '{DATA_DIR}'.")
        sys.exit(1)

    patient_ids = []

    for i, filename in enumerate(files, start=1):
        path = os.path.join(DATA_DIR, filename)
        print(f"[{i}/{len(files)}] Uploading {filename} ...")

        try:
            patient_id = upload_bundle(path)
        except requests.exceptions.Timeout:
            print("    The server took too long to respond. Skipping this one.")
            patient_id = None
        except requests.exceptions.ConnectionError:
            print("    Could not reach the server. Is it down? Skipping.")
            patient_id = None
        except requests.exceptions.HTTPError as error:
            print(f"    The server rejected this bundle: {error}. Skipping.")
            patient_id = None

        if patient_id:
            print(f"    Created Patient ID: {patient_id}")
            patient_ids.append(patient_id)
        else:
            print("    No Patient ID found for this bundle.")

        if i < len(files):
            time.sleep(DELAY_SECONDS)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(patient_ids) + ("\n" if patient_ids else ""))

    print()
    print(f"Done. {len(patient_ids)} of {len(files)} bundles uploaded.")
    print(f"Patient IDs saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
