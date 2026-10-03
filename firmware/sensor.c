#define F_CPU 16000000UL

#include <avr/io.h>
#include <util/delay.h>

static void uart_init(void) {
    UBRR0H = 0;
    UBRR0L = 103; /* 9600 baud at 16 MHz */
    UCSR0B = (1 << RXEN0) | (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

static void uart_send_char(char c) {
    while (!(UCSR0A & (1 << UDRE0))) {
    }
    UDR0 = c;
}

static void uart_send_text(const char *text) {
    while (*text) {
        uart_send_char(*text++);
    }
}

int main(void) {
    uart_init();
    uart_send_text("QEMU_READY\n");

    while (1) {
        if (UCSR0A & (1 << RXC0)) {
            char input = UDR0;
            if (input == 'M') {
                uart_send_text("MOVEMENT\n");
            }
        }
        _delay_ms(10);
    }
}

