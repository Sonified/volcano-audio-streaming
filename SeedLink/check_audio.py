import sounddevice as sd

print("Checking audio devices...")
print("-" * 50)

try:
    devices = sd.query_devices()
    print(f"Total devices found: {len(devices)}")
    print("\nAll devices:")
    for i, dev in enumerate(devices):
        print(f"\nDevice {i}:")
        print(f"  Name: {dev['name']}")
        print(f"  Channels: in={dev['max_input_channels']}, out={dev['max_output_channels']}")
        print(f"  Default sample rate: {dev['default_samplerate']}")
    
    print("\n" + "-" * 50)
    print(f"Default input device: {sd.default.device[0]}")
    print(f"Default output device: {sd.default.device[1]}")
    
    # Try to find first output device
    output_devices = [i for i, d in enumerate(devices) if d['max_output_channels'] > 0]
    if output_devices:
        print(f"\nAvailable output devices: {output_devices}")
        print(f"Recommended device ID: {output_devices[0]}")
    else:
        print("\nWARNING: No output devices found!")
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

