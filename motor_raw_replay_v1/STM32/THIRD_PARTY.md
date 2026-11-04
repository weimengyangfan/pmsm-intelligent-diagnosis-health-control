# Third-party sources

- STMicroelectronics cmsis-device-f4 v2.6.10: device headers, startup and system
  template. https://github.com/STMicroelectronics/cmsis-device-f4/tree/v2.6.10
  License retained at `Drivers/CMSIS/Device/ST/STM32F4xx/LICENSE.md`.
- ARM CMSIS 5.7.0 core headers: copied from the installed official Keil pack.
  License retained at `Drivers/CMSIS/LICENSE.txt`.
- Device pack used by Keil: Keil.STM32F4xx_DFP 3.1.1, installed from the existing
  local `C:/pack/Keil.STM32F4xx_DFP.3.1.1.pack` into the configured pack root.

Application code uses CMSIS register definitions; HAL and StdPeriph are not required.
