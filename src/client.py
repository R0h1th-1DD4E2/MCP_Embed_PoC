#!/usr/bin/env python3
"""
Enhanced CLI client for Arduino MCP Server with better debugging
"""
import asyncio
import json
import sys
import os
from typing import Dict, Any, Optional

class ArduinoMCPClient:
    def __init__(self):
        self.server_process = None
        self.request_id = 0
    
    def get_next_id(self) -> int:
        """Get next request ID"""
        self.request_id += 1
        return self.request_id
    
    async def start_server(self):
        """Start the MCP server as subprocess with better error handling"""
        try:
            print("🔄 Starting MCP server...")
            
            # Check if main.py exists
            if not os.path.exists("main.py"):
                raise Exception("main.py not found in current directory")
            
            # Start server with stderr capture
            self.server_process = await asyncio.create_subprocess_exec(
                sys.executable, "main.py",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            print("📡 Server process started, waiting for initialization...")
            
            # Wait a bit for server to start
            await asyncio.sleep(3)
            
            # Check if process is still running
            if self.server_process.returncode is not None:
                # Process has died, get the error
                stdout, stderr = await self.server_process.communicate()
                error_msg = stderr.decode() if stderr else "Unknown error"
                stdout_msg = stdout.decode() if stdout else "No output"
                
                raise Exception(f"Server process died during startup.\nSTDERR: {error_msg}\nSTDOUT: {stdout_msg}")
            
            # Try to initialize MCP connection
            await self.initialize_connection()
            print("✅ MCP Server started and initialized successfully")
            
        except Exception as e:
            print(f"❌ Failed to start server: {e}")
            if self.server_process and self.server_process.returncode is None:
                print("🔄 Attempting to read server output for debugging...")
                try:
                    # Try to read any available output
                    stdout_data = b""
                    stderr_data = b""
                    
                    # Non-blocking read attempt
                    try:
                        stdout_data = await asyncio.wait_for(
                            self.server_process.stdout.read(1024), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        pass
                    
                    try:
                        stderr_data = await asyncio.wait_for(
                            self.server_process.stderr.read(1024), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        pass
                    
                    if stdout_data:
                        print(f"📤 Server STDOUT: {stdout_data.decode()}")
                    if stderr_data:
                        print(f"📤 Server STDERR: {stderr_data.decode()}")
                        
                except Exception as debug_e:
                    print(f"⚠️  Could not read server output: {debug_e}")
            
            raise
    
    async def initialize_connection(self):
        """Initialize MCP connection with handshake"""
        try:
            print("🤝 Initializing MCP connection...")
            
            # Send initialize request
            init_request = {
                "jsonrpc": "2.0",
                "id": self.get_next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "clientInfo": {
                        "name": "Arduino MCP Client",
                        "version": "1.0.0"
                    }
                }
            }
            
            response = await self.send_raw_request(init_request)
            if "error" in response:
                raise Exception(f"Initialization failed: {response['error']}")
            
            print("📋 Initialize request successful")
            
            # Send initialized notification
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            
            await self.send_notification(initialized_notification)
            print("📢 Initialized notification sent")
            
        except Exception as e:
            print(f"❌ MCP initialization failed: {e}")
            raise
    
    async def send_raw_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Send raw JSON-RPC request to MCP server"""
        if not self.server_process:
            raise Exception("Server not started")
        
        if self.server_process.returncode is not None:
            raise Exception("Server process has died")
        
        request_json = json.dumps(request) + "\n"
        
        try:
            self.server_process.stdin.write(request_json.encode())
            await self.server_process.stdin.drain()
        except Exception as e:
            raise Exception(f"Failed to send request: {e}")
        
        # Read response with timeout
        try:
            response_line = await asyncio.wait_for(
                self.server_process.stdout.readline(), timeout=10.0
            )
        except asyncio.TimeoutError:
            raise Exception("Server response timeout")
        
        if not response_line:
            raise Exception("No response from server (connection lost)")
        
        try:
            response = json.loads(response_line.decode().strip())
            return response
        except json.JSONDecodeError as e:
            response_text = response_line.decode().strip()
            raise Exception(f"Invalid JSON response: {e}. Response was: '{response_text}'")
    
    async def send_notification(self, notification: Dict[str, Any]):
        """Send notification (no response expected)"""
        if not self.server_process:
            raise Exception("Server not started")
        
        if self.server_process.returncode is not None:
            raise Exception("Server process has died")
        
        notification_json = json.dumps(notification) + "\n"
        
        try:
            self.server_process.stdin.write(notification_json.encode())
            await self.server_process.stdin.drain()
        except Exception as e:
            raise Exception(f"Failed to send notification: {e}")
    
    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send JSON-RPC request to MCP server"""
        request = {
            "jsonrpc": "2.0",
            "id": self.get_next_id(),
            "method": method,
            "params": params or {}
        }
        
        return await self.send_raw_request(request)
    
    async def test_connection(self):
        """Test if server is responsive"""
        try:
            print("🔍 Testing server connection...")
            response = await self.send_request("tools/list")
            if "error" in response:
                print(f"⚠️  Server responded with error: {response['error']}")
                return False
            else:
                tools = response.get("result", {}).get("tools", [])
                print(f"✅ Server responsive. Found {len(tools)} tools.")
                return True
        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False
    
    async def list_tools(self):
        """List available tools"""
        response = await self.send_request("tools/list")
        if "error" in response:
            raise Exception(f"Failed to list tools: {response['error']}")
        return response.get("result", {}).get("tools", [])
    
    async def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Call a specific tool"""
        params = {
            "name": name,
            "arguments": arguments or {}
        }
        response = await self.send_request("tools/call", params)
        
        if "error" in response:
            return {"success": False, "error": response["error"]}
        
        # Parse the result from MCP response
        result = response.get("result", {})
        content = result.get("content", [])
        
        if content and len(content) > 0:
            try:
                # Try to parse JSON from the text content
                text_content = content[0].get("text", "{}")
                return json.loads(text_content)
            except json.JSONDecodeError:
                # If not JSON, return raw text
                return {"success": True, "content": text_content}
        
        return {"success": False, "error": "No content in response"}
    
    async def interactive_session(self):
        """Run interactive CLI session"""
        print("🤖 Arduino + AI MCP Client")
        print("Commands: test, led, ir, status, debug, ping, ask, analyze, smart, tools, help, quit")
        print("-" * 60)
        
        # Test connection first
        if not await self.test_connection():
            print("⚠️  Warning: Server connection issues detected")
        
        while True:
            try:
                command = input("\n> ").strip().lower()
                
                if command in ["quit", "exit", "q"]:
                    break
                elif command == "help":
                    self.show_help()
                elif command == "test":
                    await self.test_connection()
                elif command == "debug":
                    await self.handle_debug_command()
                elif command == "ping":
                    await self.handle_ping_command()
                elif command == "led":
                    await self.handle_led_command()
                elif command == "ir":
                    await self.handle_ir_command()
                elif command == "status":
                    await self.handle_status_command()
                elif command == "ask":
                    await self.handle_ask_command()
                elif command == "analyze":
                    await self.handle_analyze_command()
                elif command == "smart":
                    await self.handle_smart_command()
                elif command == "tools":
                    await self.handle_tools_command()
                elif command == "":
                    continue  # Skip empty input
                else:
                    print("❌ Unknown command. Type 'help' for available commands.")
            
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def show_help(self):
        """Show help message"""
        help_text = """
📋 Available Commands:
  test    - Test server connection
  debug   - Run Arduino communication debug
  ping    - Test Arduino communication
  led     - Control LED (ON/OFF)
  ir      - Read IR sensor value
  status  - Check Arduino connection status
  ask     - Ask AI a question
  analyze - Get AI analysis of current sensor data
  smart   - AI-controlled LED based on scenario
  tools   - List all available MCP tools
  help    - Show this help message
  quit/q  - Exit the program
        """
        print(help_text)
    
    async def handle_led_command(self):
        """Handle LED control command"""
        state = input("💡 LED state (ON/OFF): ").strip().upper()
        if state not in ["ON", "OFF"]:
            print("❌ Invalid state. Use ON or OFF")
            return
        
        print(f"🔄 Setting LED to {state}...")
        result = await self.call_tool("led_control", {"state": state})
        
        if result.get("success"):
            print(f"✅ LED set to {state}")
            if result.get("response"):
                print(f"📝 Arduino response: {result['response']}")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown error')}")
    
    async def handle_ir_command(self):
        """Handle IR sensor reading"""
        print("🔄 Reading IR sensor...")
        result = await self.call_tool("read_ir_sensor")
        
        if result.get("success"):
            ir_value = result.get("ir_sensor_value")
            interpretation = result.get("interpretation")
            print(f"📊 IR Sensor: {ir_value} - {interpretation}")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown error')}")
    
    async def handle_status_command(self):
        """Handle Arduino status check"""
        print("🔄 Checking Arduino status...")
        result = await self.call_tool("get_arduino_status")
        
        if result.get("connected"):
            print(f"✅ Arduino connected on {result.get('port')} at {result.get('baudrate')} baud")
        else:
            print("❌ Arduino not connected")
    
    async def handle_ask_command(self):
        """Handle AI question"""
        question = input("🤔 Ask AI: ").strip()
        if not question:
            print("❌ Please enter a question")
            return
        
        print("🔄 Asking AI...")
        result = await self.call_tool("ask_ai", {"question": question})
        
        if result.get("success"):
            print(f"🤖 AI Answer: {result.get('answer')}")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown error')}")
    
    async def handle_analyze_command(self):
        """Handle sensor analysis"""
        print("🔄 Reading sensor for analysis...")
        
        # First read current IR sensor
        ir_result = await self.call_tool("read_ir_sensor")
        if not ir_result.get("success"):
            print(f"❌ Failed to read IR sensor: {ir_result.get('error')}")
            return
        
        ir_value = ir_result["ir_sensor_value"]
        print(f"📊 Current IR value: {ir_value}")
        
        context = input("📝 Context for analysis (optional): ").strip()
        
        print("🔄 Getting AI analysis...")
        result = await self.call_tool("analyze_sensor_with_ai", {
            "ir_value": ir_value,
            "context": context
        })
        
        if result.get("success"):
            print(f"🤖 AI Analysis:\n{result.get('ai_analysis')}")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown error')}")
    
    async def handle_smart_command(self):
        """Handle smart LED control"""
        scenario = input("📝 Describe the scenario: ").strip()
        if not scenario:
            print("❌ Please describe the scenario")
            return
        
        print("🔄 AI is analyzing scenario and controlling LED...")
        result = await self.call_tool("smart_led_control", {"scenario": scenario})
        
        if result.get("success"):
            print(f"🤖 AI Decision: {result.get('ai_decision')}")
            print(f"📊 IR Sensor was: {result.get('ir_sensor')}")
            led_action = result.get("led_action", {})
            if led_action.get("success"):
                print(f"💡 LED set to: {led_action.get('led_state')}")
            else:
                print(f"❌ LED control failed: {led_action.get('error')}")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown error')}")
    
    async def handle_tools_command(self):
        """List all available tools"""
        print("🔄 Fetching available tools...")
        try:
            tools = await self.list_tools()
            print(f"\n🛠️  Available Tools ({len(tools)}):")
            for i, tool in enumerate(tools, 1):
                print(f"  {i}. {tool['name']}")
                print(f"     📝 {tool['description']}")
        except Exception as e:
            print(f"❌ Failed to fetch tools: {e}")
    
    async def handle_debug_command(self):
        """Handle Arduino debug command"""
        print("🔄 Running Arduino communication debug...")
        result = await self.call_tool("debug_arduino_raw")
        
        if result.get("success"):
            debug_results = result.get("debug_results", {})
            for cmd, data in debug_results.items():
                print(f"\n🔍 Command: {cmd}")
                if data.get("error"):
                    print(f"  ❌ Error: {data['error']}")
                else:
                    responses = data.get("responses", [])
                    print(f"  ✅ Responses: {responses}")
        else:
            print(f"❌ Debug failed: {result.get('error', 'Unknown error')}")
    
    async def handle_ping_command(self):
        """Handle Arduino ping test"""
        print("🔄 Pinging Arduino...")
        result = await self.call_tool("test_arduino_communication")
        
        if result.get("success"):
            print(f"✅ Arduino responded: {result.get('response')}")
            if result.get("all_responses"):
                print(f"📋 All responses: {result.get('all_responses')}")
        else:
            print(f"❌ Ping failed: {result.get('error', 'Unknown error')}")
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.server_process:
            print("🔄 Shutting down MCP server...")
            
            # Check if process is still alive before trying to terminate
            if self.server_process.returncode is None:
                try:
                    self.server_process.terminate()
                    await asyncio.wait_for(self.server_process.wait(), timeout=5.0)
                    print("✅ Server shut down gracefully")
                except asyncio.TimeoutError:
                    print("⚠️  Server didn't shut down gracefully, killing...")
                    self.server_process.kill()
                    await self.server_process.wait()
                    print("🔪 Server killed")
                except ProcessLookupError:
                    print("ℹ️  Server process already terminated")
            else:
                print("ℹ️  Server process was already terminated")

async def main():
    client = ArduinoMCPClient()
    
    try:
        print("🚀 Starting Arduino MCP Client...")
        await client.start_server()
        await client.interactive_session()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        await client.cleanup()

if __name__ == "__main__":
    # Check if we're in the right directory
    if not os.path.exists("main.py"):
        print("❌ main.py not found in current directory!")
        print("Please run this client from the directory containing main.py")
        sys.exit(1)
    
    asyncio.run(main())
