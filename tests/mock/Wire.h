#pragma once
#include <cstdint>
struct FakeWire {
 void setSDA(int){} void setSCL(int){} void begin(){} void setClock(unsigned long){}
 void beginTransmission(uint8_t){} void write(uint8_t){} int endTransmission(bool=true){return 0;}
 int requestFrom(uint8_t,uint8_t){return 4;} int available(){return 0;}int read(){return 0;}
};
extern FakeWire Wire;
