idf_component_register(SRCS "main.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_timer esp_driver_uart esp_netif esp_event lwip)
