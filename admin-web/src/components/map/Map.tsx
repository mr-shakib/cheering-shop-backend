/* Leaflet with OpenStreetMap tiles. Tiles are plain <img> loads (the admin
 * CSP allows https images), and markers are CSS-drawn DivIcons, so nothing
 * depends on Leaflet's bundled marker PNGs. */
import { useEffect } from "react";
import L from "leaflet";
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";

export const DHAKA: [number, number] = [23.8103, 90.4125];

export function pinIcon(tone: "brand" | "green" | "orange" | "gray" = "brand", active = false) {
  return L.divIcon({
    className: "",
    html: `<span class="map-pin map-pin-${tone}${active ? " map-pin-active" : ""}"></span>`,
    iconSize: [28, 36],
    iconAnchor: [14, 34],
  });
}

export function Tiles() {
  return (
    <TileLayer
      url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      maxZoom={19}
    />
  );
}

function ClickToPlace({ onPick }: { onPick: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

function Recenter({ center }: { center: [number, number] }) {
  const map = useMap();
  useEffect(() => {
    if (!map.getBounds().contains(center)) map.setView(center);
  }, [center, map]);
  return null;
}

/** Click or drag to set a location. */
export function LocationPicker({
  lat,
  lng,
  onChange,
  className,
}: {
  lat: number | null;
  lng: number | null;
  onChange: (lat: number, lng: number) => void;
  className?: string;
}) {
  const has = lat !== null && lng !== null;
  const center: [number, number] = has ? [lat, lng] : DHAKA;
  const round = (n: number) => Math.round(n * 1e6) / 1e6;
  return (
    <MapContainer center={center} zoom={has ? 15 : 12} className={className ?? "h-72 w-full rounded-lg"} scrollWheelZoom={false}>
      <Tiles />
      <ClickToPlace onPick={(a, b) => onChange(round(a), round(b))} />
      {has && (
        <>
          <Recenter center={center} />
          <Marker
            position={center}
            icon={pinIcon("brand")}
            draggable
            eventHandlers={{
              dragend: (e) => {
                const p = (e.target as L.Marker).getLatLng();
                onChange(round(p.lat), round(p.lng));
              },
            }}
          />
        </>
      )}
    </MapContainer>
  );
}
