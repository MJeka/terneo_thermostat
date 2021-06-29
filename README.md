# Terneo Thermostat
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Компонент Terneo Thermostat для Home Assistant

Версия прошивки устройства должна быть >= 2.3

Документация по АПИ - https://terneo-api.readthedocs.io/ru/latest/

>В версии прошивки 2.3 возможность управления локальной сетью по умолчанию заблокирована из соображений безопасности.

Удаление блокировки - https://terneo-api.readthedocs.io/ru/latest/ru/safety_ru.html

Два варианта установки:

 - поместите папку `terneo` в папку` custom_components` и перезагрузите HA.
 - С HACS: войдите в HACS, нажмите «Интеграции», нажмите на три маленькие точки в верхней части экрана и выберите «Пользовательские репозитории», добавьте этот URL-адрес github, выберите «Интеграция» в качестве репозитория и нажмите ДОБАВИТЬ. Затем перейдите на вкладку «Интеграции» HACS и установите интеграцию «Terneo Thermostat».

Пример конфигурации (`configuration.yaml`):

```
climate:
  - platform: terneo
    serial: 'DEVICE_SERIALNUMBER'
    host: 'DEVICE_IP'
```
Серийный номер устройства можно узнать зайдя по адресу устройства - http://`{device_ip}`/index.html
в личном кабине на сайте https://my.terneo.ua/ или в мобильном приложении


# Terneo Thermostat
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Terneo Thermostat component for Home Assistant

required device firmware version 2.3

https://terneo-api.readthedocs.io/ru/latest/

>In firmware version 2.3, the ability to control the local network by default blocked for security reasons.

block removing - https://terneo-api.readthedocs.io/ru/latest/en/safety.html

Two possibilities for installation:

 - put `terneo` folder to the `custom_components` folder and reboot HA.
 - With HACS: go in HACS, click on Integrations, click on the three little dots at top of the screen and selection "custom repositories", add this github url, select "Integration" as repository, and click ADD. Then go to the Integrations tab of HACS, and install the "Terneo Thermostat" integration.

config example (`configuration.yaml`):

```
climate:
  - platform: terneo
    serial: 'DEVICE_SERIALNUMBER'
    host: 'DEVICE_IP'
```
serial number can be found on the page  http://`{device_ip}`/index.html
