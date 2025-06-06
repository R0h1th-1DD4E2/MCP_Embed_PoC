#!/usr/bin/env python3
import asyncio
import json
import os
import serial
import serial.tools.list_ports
import time
from mcp.server.fastmcp import FastMCP
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class ArduinoMCPServer:
    def __init__(self, port=None, baudrate=9600):
        self.mcp = FastMCP("Arduino AI Controller")
        self.arduino = None
        self.port = port
        self.baudrate = baudrate
        
        # Initialize components
        self.setup_arduino()
        self.setup_gemini()
        self.setup_tools()
    
    def setup_arduino(self):
        """Initialize Arduino connection"""
        if self.port is None:
            # Auto-detect Arduino
            ports = serial.tools.list_ports.comports()
            for port in ports:
                if 'Arduino' in port.description or 'ttyUSB' in port.device or 'ttyACM' in port.device:
                    self.port = port.device
                    break
        
        if self.port is None:
            print("No Arduino found. Please specify port manually.")
            return
        
        try:
            self.arduino = serial.Serial(self.port, self.baudrate, timeout=2)
            time.sleep(2)  # Wait for Arduino to initialize
            
            # Clear any initial garbage from the buffer
            self.arduino.flushInput()
            self.arduino.flushOutput()
            
            print(f"Arduino connected on {self.port}")
        except Exception as e:
            print(f"Failed to connect to Arduino: {e}")
            self.arduino = None
    
    def arduino_send_command(self, command, expected_response_lines=1, retry_count=3):
        """Send command to Arduino with robust error handling"""
        if not self.arduino:
            return None, "Arduino not connected"
        
        for attempt in range(retry_count):
            try:
                # Clear buffers
                self.arduino.flushInput()
                self.arduino.flushOutput()
                
                # Send command
                full_command = f"{command}\n"
                self.arduino.write(full_command.encode())
                time.sleep(0.2)  # Give Arduino time to process
                
                # Read response(s)
                responses = []
                for _ in range(expected_response_lines):
                    response = self.arduino.readline().decode().strip()
                    if response:  # Only add non-empty responses
                        responses.append(response)
                    else:
                        # Try reading again with a bit more delay
                        time.sleep(0.1)
                        response = self.arduino.readline().decode().strip()
                        if response:
                            responses.append(response)
                
                if responses:
                    return responses, None
                else:
                    print(f"Attempt {attempt + 1}: No response from Arduino for command '{command}'")
                    time.sleep(0.5)  # Wait before retry
                    
            except Exception as e:
                print(f"Attempt {attempt + 1}: Arduino communication error: {e}")
                time.sleep(0.5)
        
        return None, f"Failed to get response from Arduino after {retry_count} attempts"
    
    def setup_gemini(self):
        """Initialize Gemini API"""
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        
        genai.configure(api_key=api_key)
        
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-exp",
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 1024,
            }
        )
        
        self.chat = self.model.start_chat(history=[])
        print("Gemini AI initialized")
    
    def setup_tools(self):
        """Setup MCP tools"""
        
        @self.mcp.tool()
        def led_control(state: str) -> dict:
            """Control the LED on Arduino (ON/OFF)"""
            if not self.arduino:
                return {"success": False, "error": "Arduino not connected"}
            
            if state not in ["ON", "OFF"]:
                return {"success": False, "error": "State must be 'ON' or 'OFF'"}
            
            responses, error = self.arduino_send_command(f"LED:{state}")
            
            if error:
                return {"success": False, "error": error}
            
            return {
                "success": True,
                "command": f"LED:{state}",
                "response": responses[0] if responses else "No response",
                "led_state": state
            }
        
        @self.mcp.tool()
        def read_ir_sensor() -> dict:
            """Read the IR sensor value from Arduino"""
            if not self.arduino:
                return {"success": False, "error": "Arduino not connected"}
            
            responses, error = self.arduino_send_command("IR?")
            
            if error:
                return {"success": False, "error": error}
            
            if not responses:
                return {"success": False, "error": "No response from Arduino"}
            
            try:
                # Try to parse the response
                response_text = responses[0].strip()
                
                # Handle different possible response formats
                if response_text.isdigit():
                    ir_value = int(response_text)
                elif ':' in response_text:
                    # Handle format like "IR:1" or "IR_VALUE:1"
                    ir_value = int(response_text.split(':')[-1])
                else:
                    # If we can't parse it, return the raw response for debugging
                    return {
                        "success": False, 
                        "error": f"Could not parse IR response: '{response_text}'"
                    }
                
                return {
                    "success": True,
                    "ir_sensor_value": ir_value,
                    "interpretation": "Object detected" if ir_value == 1 else "No object detected",
                    "raw_response": response_text
                }
                
            except (ValueError, IndexError) as e:
                return {
                    "success": False, 
                    "error": f"Failed to parse IR sensor value: {e}. Raw response: '{responses[0] if responses else 'None'}'"
                }
        
        @self.mcp.tool()
        def test_arduino_communication() -> dict:
            """Test Arduino communication with a simple ping"""
            if not self.arduino:
                return {"success": False, "error": "Arduino not connected"}
            
            # Try a simple command that should always work
            responses, error = self.arduino_send_command("PING")
            
            if error:
                return {"success": False, "error": error}
            
            return {
                "success": True,
                "response": responses[0] if responses else "No response",
                "all_responses": responses
            }
        
        @self.mcp.tool()
        def get_arduino_status() -> dict:
            """Get Arduino connection status"""
            status = {
                "connected": self.arduino is not None,
                "port": self.port,
                "baudrate": self.baudrate
            }
            
            if self.arduino:
                try:
                    status["is_open"] = self.arduino.is_open
                    status["timeout"] = self.arduino.timeout
                except:
                    status["connection_error"] = "Could not read port status"
            
            return status
        
        @self.mcp.tool()
        def debug_arduino_raw() -> dict:
            """Debug tool to send raw commands and see responses"""
            if not self.arduino:
                return {"success": False, "error": "Arduino not connected"}
            
            # Try multiple commands to debug
            debug_results = {}
            
            commands_to_test = ["PING", "IR?", "LED:ON", "LED:OFF", "STATUS"]
            
            for cmd in commands_to_test:
                responses, error = self.arduino_send_command(cmd)
                debug_results[cmd] = {
                    "responses": responses,
                    "error": error
                }
            
            return {
                "success": True,
                "debug_results": debug_results
            }
        
        @self.mcp.tool()
        def ask_ai(question: str) -> dict:
            """Ask Gemini AI anything"""
            try:
                response = self.chat.send_message(question)
                
                return {
                    "success": True,
                    "question": question,
                    "answer": response.text
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        @self.mcp.tool()
        def analyze_sensor_with_ai(ir_value: int, context: str = "") -> dict:
            """Use AI to analyze IR sensor data and suggest actions"""
            try:
                prompt = f"""
                Analyze this IR sensor reading from an Arduino:
                
                IR Sensor Value: {ir_value} (0 = no object detected, 1 = object detected)
                Context: {context if context else "General sensing"}
                
                Please provide:
                1. What this sensor reading means
                2. Possible actions to take
                3. Any safety considerations
                
                Keep response concise and practical.
                """
                
                response = self.chat.send_message(prompt)
                
                return {
                    "success": True,
                    "ir_value": ir_value,
                    "context": context,
                    "ai_analysis": response.text
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        @self.mcp.tool()
        def smart_led_control(scenario: str) -> dict:
            """Use AI to decide LED state based on sensor data"""
            try:
                # First get current IR sensor reading
                ir_result = read_ir_sensor()
                
                if not ir_result["success"]:
                    return ir_result
                
                ir_value = ir_result["ir_sensor_value"]
                
                prompt = f"""
                You're controlling an Arduino with LED and IR sensor. Current situation:
                
                IR Sensor: {ir_value} (0 = no object, 1 = object detected)
                Scenario: {scenario}
                
                Should the LED be ON or OFF? Start your response with exactly "LED:ON" or "LED:OFF" followed by your reason.
                """
                
                ai_response = self.chat.send_message(prompt)
                ai_text = ai_response.text.strip()
                
                # Simple and reliable parsing
                if ai_text.upper().startswith("LED:ON"):
                    led_state = "ON"
                elif ai_text.upper().startswith("LED:OFF"):
                    led_state = "OFF"
                else:
                    # If AI doesn't follow format, check which word appears first
                    if "OFF" in ai_text.upper() and ai_text.upper().find("OFF") < ai_text.upper().find("ON"):
                        led_state = "OFF"
                    else:
                        led_state = "ON"
                
                # Execute the LED control
                led_result = led_control(led_state)
                
                return {
                    "success": True,
                    "scenario": scenario,
                    "ir_sensor": ir_value,
                    "ai_decision": ai_response.text,
                    "led_action": led_result
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
    
    def run(self):
        """Run the MCP server"""
        self.mcp.run()

def main():
    """Main entry point"""
    try:
        # You can specify Arduino port manually if needed
        # server = ArduinoMCPServer(port="/dev/ttyUSB0")
        server = ArduinoMCPServer()  # Auto-detect
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    except Exception as e:
        print(f"Failed to start server: {e}")

if __name__ == "__main__":
    main()
