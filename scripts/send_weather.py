import asyncio
import click
import requests
import io
from PIL import Image, ImageDraw, ImageFont
from zhsunyco_esl import ZhsunycoClient, LabelConfig

# WMO Weather Codes to Icon Names (using a public icon set)
# We will use keys that map to filenames if we were downloading specific packs, 
# or use a generic mapping logic. 
# For "beautiful" we want distinct icons. 
# Open-Meteo codes: https://open-meteo.com/en/docs
# 0: Clear sky
# 1, 2, 3: Mainly clear, partly cloudy, overcast
# 45, 48: Fog
# 51-55: Drizzle
# 61-65: Rain
# 71-77: Snow
# 80-82: Rain showers
# 85-86: Snow showers
# 95-99: Thunderstorm

def get_weather():
    url = "https://api.open-meteo.com/v1/forecast?latitude=51.5074&longitude=-0.1278&current=temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m&units=metric"
    try:
        r = requests.get(url)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error fetching weather: {e}")
        return None

def get_icon_url(code, is_day=1):
    # Using a reliable public icon set. 
    # OpenWeatherMap icons are easy but low res. 
    # Let's use 'weather-icons' mapping if possible, or just OpenWeatherMap 4x.
    # OpenWeatherMap 4x is actually decent for small screens if dithered.
    
    # Simple mapping from WMO to OWM codes
    # 0 -> 01d/n
    # 1 -> 02d/n
    # 2 -> 03d/n
    # 3 -> 04d/n
    # 45,48 -> 50d
    # 51-67 -> 09d (rain) or 10d (rain with sun)
    # 71-77 -> 13d (snow)
    # 95 -> 11d (thunder)
    
    mapping = {
        0: '01d', 1: '02d', 2: '03d', 3: '04d',
        45: '50d', 48: '50d',
        51: '09d', 53: '09d', 55: '09d',
        56: '09d', 57: '09d',
        61: '10d', 63: '10d', 65: '10d',
        66: '10d', 67: '10d',
        71: '13d', 73: '13d', 75: '13d', 77: '13d',
        80: '09d', 81: '09d', 82: '09d',
        85: '13d', 86: '13d',
        95: '11d', 96: '11d', 99: '11d'
    }
    
    icon_code = mapping.get(code, '03d')
    return f"https://openweathermap.org/img/wn/{icon_code}@4x.png"

def get_condition_text(code):
    codes = {
        0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing Rime Fog",
        51: "Light Drizzle", 53: "Moderate Drizzle", 55: "Dense Drizzle",
        56: "Light Freezing Drizzle", 57: "Dense Freezing Drizzle",
        61: "Slight Rain", 63: "Moderate Rain", 65: "Heavy Rain",
        66: "Light Freezing Rain", 67: "Heavy Freezing Rain",
        71: "Slight Snow Fall", 73: "Moderate Snow Fall", 75: "Heavy Snow Fall", 77: "Snow Grains",
        80: "Slight Rain Showers", 81: "Moderate Rain Showers", 82: "Violent Rain Showers",
        85: "Slight Snow Showers", 86: "Heavy Snow Showers",
        95: "Thunderstorm", 96: "Thunderstorm + Hail", 99: "Thunderstorm + Heavy Hail"
    }
    return codes.get(code, "Unknown")

@click.command()
@click.version_option()
@click.option('--mac', required=True, help='MAC address of the label')
@click.option('--color', default='BWR', type=click.Choice(['BW', 'BWR']), help='Color mode')
@click.option('--width', default=296, help='Width of the label')
@click.option('--height', default=128, help='Height of the label')
def main(mac, color, width, height):
    """Fetches weather for London and displays it on the label."""
    
    print("Fetching weather for London...")
    data = get_weather()
    if not data:
        print("Failed to get data.")
        return

    current = data['current']
    temp = current['temperature_2m']
    code = current['weather_code']
    humidity = current['relative_humidity_2m']
    wind = current['wind_speed_10m']
    
    print(f"London: {temp}°C, {get_condition_text(code)}")
    
    # Create Image
    # BWR Palette: White background
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    
    # Download Icon
    icon_url = get_icon_url(code, current.get('is_day', 1))
    try:
        print(f"Fetching icon: {icon_url}")
        resp = requests.get(icon_url, stream=True)
        resp.raise_for_status()
        icon = Image.open(resp.raw).convert("RGBA")
        
        # Resize icon. 4x is 200x200. Screen height is 128.
        # Let's make it 100x100 and put it on the left.
        icon = icon.resize((100, 100), Image.Resampling.LANCZOS)
        
        # Paste with mask
        # We need a white background for specific transparent icons
        bg_icon = Image.new("RGB", (100, 100), "white")
        bg_icon.paste(icon, (0, 0), icon)
        canvas.paste(bg_icon, (10, (height-100)//2))
    except Exception as e:
        print(f"Could not load icon: {e}")
        # Draw placeholder circle (Sun) or something
        draw.ellipse([20, 20, 100, 100], outline="black", width=3)
    
    # Fonts
    try:
        # Try to use a nice font if available, else default
        # Roboto-Bold or Arial
        try:
            large_font = ImageFont.truetype("arial.ttf", 48)
            med_font = ImageFont.truetype("arial.ttf", 20)
            small_font = ImageFont.truetype("arial.ttf", 14)
        except:
            # Fallback for linux/other
            large_font = ImageFont.load_default() 
            med_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
    except:
        pass

    # Layout
    # Left: Icon (approx 0-110)
    # Right: Text (120+)
    
    text_x = 120
    
    # City
    draw.text((text_x, 10), "LONDON", fill="black", font=small_font)
    
    # Temperature (Red if BWR, Black if BW)
    temp_color = "red" if color == "BWR" else "black"
    draw.text((text_x, 30), f"{temp:.1f}°C", fill=temp_color, font=large_font)
    
    # Condition
    condition = get_condition_text(code)
    draw.text((text_x, 85), condition, fill="black", font=med_font)
    
    # Details (Win/Hum)
    details = f"Hum: {humidity}%  Wind: {wind} km/h"
    draw.text((text_x, 110), details, fill="black", font=small_font)

    # Save debug
    # canvas.save("last_weather.png")

    # Send
    config = LabelConfig(width=width, height=height)
    client = ZhsunycoClient(mac, config=config)
    
    from zhsunyco_esl.image import process_image, dither_image
    
    print("Processing and sending...")
    plane_bw, plane_red = dither_image(canvas, width, height, color_mode=color)
    try:
        asyncio.run(client.send_image_planes(plane_bw, plane_red))
    except Exception as e:
        print(f"Error: {e}")
        ctx = click.get_current_context()
        ctx.exit(1)

if __name__ == "__main__":
    main()
