# Getting Started

1. Create the Nautobot Location hierarchy and Racks.
2. Give the user Location/Rack view permissions and Location Floor Plan map/placement permissions.
3. Open the parent Location and select **Location Floor Plan**.
4. Create a map with logical width and height.
5. Optionally upload a PNG, JPEG, or SVG background.
6. Use the picker to add unused descendant Locations and Racks.
7. Draw or edit shapes with Leaflet 1.9.4 and Geoman Free 2.20.0.
8. Save the snapshot. If another user saved first, reload after the HTTP 409 revision conflict.

Rack usage colors are calculated live from Devices mounted in the Rack; no rack usage data is stored by Location Floor Plan.
